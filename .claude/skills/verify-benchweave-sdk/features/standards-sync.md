# standards-sync

The vendored standards tree and its lock: the mechanism that makes "vendored" mean pinned
rather than copied.

## Sub-features

- **`sync-standards --check`** with no bundle — verifies the committed lock against the
  vendored tree and its stamps. Read-only, works from a repository checkout or an installed
  wheel (against the packaged lock).
- **`sync-standards <bundle> [--check]`** — imports a standards bundle into the tree and
  rewrites `standards-lock.json`. Needs a repository checkout
  (`sync_requires_repo_checkout:` when installed).

## How to get to it (user POV)

An author or CI run asks "is the vendored tree still the one the lock pins?" with
`benchweave-sdk sync-standards --check`. A maintainer taking a new standards export runs
`sync-standards <bundle>` from a checkout.

## Driving it with the CLI

```sh
uv run --no-sync benchweave-sdk sync-standards --check
```

Expected end state:

- exit 0, stdout `Standards verified (committed lock and vendored tree agree).`
- no files written — the check lane never mutates the tree

Drift arm, proving the lane is live: in a throwaway copy of the checkout, edit one byte of
a file under `src/benchweave_sdk/standards/` (never in the real tree) and require exit 1
with `standards drift detected (...)` naming `hash_mismatch`. Restore the byte and require
exit 0 again.

## Gotchas

- **Never hand-edit `src/benchweave_sdk/standards/`.** It is generated; the change belongs
  in the main repository's canonical corpus, re-exported and re-synced. A test-side guard
  (`tests/conftest.py`) fails any test that opens a write on that tree, because a write
  corrupts every concurrent reader under `-n auto`.
- **The three check lanes must stay symmetric** (STD-3): `--check` without a bundle,
  bundle-mode `--check`, and the `hatch_build.py` packaging hook. Tightening one without
  the others is drift, and this skill does not cover the packaging lane.
- **A content change needs a standards version increment** (`standards_version_required:`).
  Content moves version-first, never hash-only.
- **Importing a bundle rewrites the source tree** and refuses from an installed SDK
  (`sync_requires_repo_checkout:`). Only the `--check` form exists there.
- **A run here can mask a real problem.** If `--check` fails before your change, the tree
  was already drifted; report that separately and never fold it into your own result.
