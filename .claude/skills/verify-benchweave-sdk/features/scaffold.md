# scaffold

The command that creates a plugin project, plus the commands that keep its provenance
honest afterwards.

## Sub-features

- **`new`** — renders the copier template into a new directory. Bare, `--with-ui` (adds
  `presentation.json`, `ui/`, `binding-catalogue.json`), `--provider-transport` (pins the
  FTDI control contract, emits provider-shaped builders and a provider-dialect
  `vectors.json`).
- **`doctor`** — reads the `benchweave-sdk==` pin out of the project's test extra and
  compares it with the running SDK. Diagnoses, never fails on a mismatch.
- **`upgrade`** — moves a committed, clean git project to the installed SDK's released
  template tag. Author-owned files are preserved; a file both sides changed comes back with
  conflict markers.
- **`adopt`** — writes the provenance record for a pre-copier project.

## How to get to it (user POV)

Install with the scaffold extra (`pip install 'benchweave-sdk[scaffold]'` or
`uv tool install`), then run `benchweave-sdk new plugins/acme/model100 --package
benchweave_acme_model100`. Collect plugins under `plugins/<manufacturer>/<name>/`; the
project directory and the import package are different names, so `--package` is how the
import name is chosen.

## Driving it with the CLI

```sh
RUN_ROOT="$(mktemp -d /private/tmp/bw-verify.XXXXXX)"

uv run --no-sync benchweave-sdk new "$RUN_ROOT/plugins/acme/model100" \
  --package benchweave_acme_model100
uv run --no-sync benchweave-sdk doctor "$RUN_ROOT/plugins/acme/model100"

uv run --no-sync benchweave-sdk new "$RUN_ROOT/plugins/acme/ui100" \
  --package benchweave_acme_ui100 --with-ui
```

Expected end state:

- exit 0 and `Created synthetic plugin at <canonical path>; review before hardware or
  publication.`
- `AI-GUIDE.md`, `CLAUDE.md`, `AGENTS.md`, `pyproject.toml`, `README.md`, `src/`, `tests/`,
  `.github/`, `.claude/` under the project root
- `.copier-answers.yml` carrying the template provenance
- `doctor` printing `Scaffold version matches the installed SDK: benchweave-sdk <X.Y.Z>.`

## Gotchas

- **`/tmp` is a symlink on macOS.** `new` canonicalizes the destination and the report
  names the real path (`/private/tmp/...`). Later commands such as `check` refuse a
  symlinked component outright with `path_symlink_component:`. Use `/private/tmp` from the
  start.
- **A destination must not exist.** A second `new` at the same path fails with
  `Destination already exists: <path>` and exit 1. Scaffold a fresh name per run rather
  than deleting and reusing.
- **`scaffold_extra_absent:`** means copier is not installed. In this checkout that is a
  missing dev dependency: `uv sync`.
- **`--with-ui` is not free.** The generated project carries presentation artifacts stamped
  with a plugin-ui contract version. When the SDK moves that version, the project needs
  `migrate-ui`; `new` reports the version it stamped.
- **`upgrade` needs a committed, clean git tree** (`upgrade_requires_git:`,
  `upgrade_dirty_tree:`). It is not a way to move an uncommitted scratch project.
- The generated runtime has no dependency on this SDK; the plugin's test extra pins the SDK
  version. That pin is a mutable declaration, not provenance — `.copier-answers.yml` is the
  provenance record.
