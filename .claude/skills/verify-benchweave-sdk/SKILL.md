---
name: verify-benchweave-sdk
description: Drive the benchweave-sdk CLI for real to prove an SDK change works — scaffold a plugin into a canonical scratch dir and run the actual commands (new, doctor, check, verify-ui, check-preset, sync-standards --check, inventory, package), capturing exit codes, streams and written files as evidence. Use when a change needs proof from the real CLI rather than pytest alone, or when answering "does this still work?" before a PR.
---

# verify-benchweave-sdk

The surface a plugin author meets is the `benchweave-sdk` console script: a short-lived
click CLI with no service, no hardware and no network. Proof here means running that
script the way an author runs it — scaffold a project, check it, render it — and capturing
what came back.

The behavioural suite (`tests/`) proves the internals. This skill proves the surface.

## Launch

```sh
cd "$(git rev-parse --show-toplevel)"   # the checkout you are verifying
export UV_PROJECT_ENVIRONMENT=venv   # this checkout's venv is ./venv, not .venv
uv sync                              # once per checkout; dev deps include copier
uv run --no-sync benchweave-sdk --version
```

Ready means stdout carries `benchweave-sdk, version <X.Y.Z>`, the exit code is 0, and
`X.Y.Z` matches `grep '^version' pyproject.toml`. There is no server to keep alive: every
command starts and exits on its own, so launch is "the console script resolves to this
checkout's code" and nothing more.

Always pass `--no-sync`. A plain `uv run` re-resolves the environment before running; a
sync mid-run can swap packages under the process you are trying to measure.

Teardown is `rm -rf "$RUN_ROOT"`, the scratch directory you created, after evidence is
copied out. See Cleanup.

## Doctor

Run this first whenever a result looks wrong. It is read-only and answers "is this
checkout worth driving?"

```sh
uv run --no-sync benchweave-sdk --version                # matches pyproject.toml
uv run --no-sync benchweave-sdk sync-standards --check   # exit 0: lock/tree/stamps agree
git rev-parse --short HEAD
git status --short
```

- `sync-standards --check` failing means the vendored tree was already drifted before your
  change. Fix or report that; never attribute it to your work.
- `new` refusing with `scaffold_extra_absent:` means copier is missing: run `uv sync`.
- The `git` lines record what drift already existed, so a dirty tree is never mistaken for
  your change.

## Drive

Scratch root, one per run, created canonical:

```sh
RUN_ROOT="$(mktemp -d /private/tmp/bw-verify.XXXXXX)"
```

On macOS `/tmp` is a symlink to `/private/tmp`, and every path-taking command canonicalizes
and refuses symlink components with `path_symlink_component:`. Use `/private/tmp/...`
everywhere. A destination must not already exist.

Every command runs from the repo root with absolute paths:

| Goal | Command (prefix each with `uv run --no-sync benchweave-sdk`) |
|---|---|
| scaffold a plugin | `new "$RUN_ROOT/plugins/acme/model100" --package benchweave_acme_model100` |
| scaffold with presentation | add `--with-ui` to `new` |
| scaffold with a transport provider | add `--provider-transport` to `new` |
| check the pinned SDK version | `doctor "$RUN_ROOT/plugins/acme/model100"` |
| descriptor check | `check "$RUN_ROOT/plugins/acme/model100/src/benchweave_acme_model100/descriptor.json"` |
| render gate | `verify-ui "$RUN_ROOT/plugins/acme/ui100"` |
| full settings check | `check-preset <preset.json> --descriptor <d> --settings-schema <s>` |
| presentation envelope | `check-ui <presentation.json> --descriptor <d> --resources <r> --catalogue <c>` |
| bundle hashes | `inventory "$RUN_ROOT/plugins/acme/model100"` |
| package an artefact set | `package <plugin> --registry-clone <clone> --source-url <u> --revision <40-or-64-hex> --publisher <id> --out <dir>` |
| standards integrity | `sync-standards --check` |
| preview on the standalone host | `preview-ui <project> --port <free> --no-open` |

There is no DOM, so there are no selectors. The stable handles, in order of preference:

1. **Exit code** — 0 pass, 1 a refusal or check failure, 2 a usage error.
2. **A `snake_case:` refusal prefix** — STD-4 makes refusal prefixes the API
   (`path_symlink_component:`, `scaffold_extra_absent:`, `standards_version_required:`,
   `migrate_ui_ahead:`, `benchweave_sdk_server_extras_missing:`). Assert the prefix.
3. **A written file's path or a machine-readable shape** — the generated tree,
   `descriptor.json`, `.copier-answers.yml`; `inventory` prints JSON on stdout.

Never assert on full English prose. The messages churn between releases; the prefix and
the code do not.

## Evidence

Write every proof to `<repo>/.verify/<run-id>/`, which is gitignored and sits outside the
scratch root so cleanup cannot eat it:

```
doctor.txt          # doctor output, HEAD, git status
transcript.tsv      # one row per command: <name>\t<exit>
<name>.stdout       # captured stdout
<name>.stderr       # captured stderr
tree.txt            # find "$RUN_ROOT" -type f | sort
summary.md          # what was driven, what each exit code means
```

Proof standards for this repo:

- Drive the real user path. `new` then `check` on the generated descriptor — not
  `validation.py` called directly, not a test-only endpoint.
- Capture the action and the resulting state. The exit code alone is not the proof; pair it
  with `tree.txt` and with the JSON `inventory` emits.
- Verify side effects. A `--with-ui` scaffold must show `presentation.json`, `ui/` and
  `binding-catalogue.json` in the package; a bare one must not.
- A refusal is proven three ways: exit code, prefix, and the absence of the write. A
  refused `migrate-ui` or `sync-standards` writes nothing — check the tree before and after.
- State what the CLI does **not** prove. `check` is the descriptor schema plus basic
  S01/S02/S04 only; the full S01–S18, C01–C12 and M01–M14 obligations and all hardware
  evidence remain separate. `verify-ui` renders a gate — it is not admission, qualification
  or approval to apply settings. Say so in `summary.md` rather than letting a green exit
  code imply more.

## Cleanup

```sh
rm -rf "$RUN_ROOT"
```

That is the only thing a run creates. Never kill by process name (`pkill benchweave`,
`killall python`) — for `preview-ui`, record the PID with `$!` and `kill "$PID"`. Evidence
lives in `.verify/`, which is outside `$RUN_ROOT`; after teardown, confirm the evidence
files still exist before reporting the run.

## Helpers

`capture.sh` runs one command and records its exit code and both streams. Invoke it from
anywhere; it resolves the repo root from its own location and sets
`UV_PROJECT_ENVIRONMENT=venv`.

```sh
.claude/skills/verify-benchweave-sdk/capture.sh <evidence-dir> <name> -- <sdk args...>
.claude/skills/verify-benchweave-sdk/capture.sh "$EV" new-check -- check "$DESCRIPTOR"
```

It appends `<name>\t<exit>` to `<evidence-dir>/transcript.tsv` and exits with the command's
own code, so a script can branch on it.

## Feature map

`.claude/skills/verify-benchweave-sdk/features/` holds one file per user-facing feature —
the seed map has five: `scaffold`, `descriptor-check`, `presentation`, `standards-sync` and
`packaging`. Read `features/README.md` for the index. Keep the map honest with
`/pstack:maintain-verification-skill` as the app changes.
