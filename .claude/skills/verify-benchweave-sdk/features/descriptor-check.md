# descriptor-check

The offline conformance gate a plugin author runs against the descriptor before touching
hardware or publication.

## Sub-features

- **`check <descriptor.json>`** — the descriptor's schema plus the basic semantic checks
  S01, S02 and S04. Exit 0 passes, exit 1 refuses.
- Nothing else. Full conformance is not this command; see Gotchas.

## How to get to it (user POV)

After scaffolding and editing `src/<package>/descriptor.json`, run
`benchweave-sdk check src/<package>/descriptor.json` from the plugin project. `doctor`
tells you whether the installed SDK is the one the project pins; `check` tells you whether
the descriptor is well formed.

## Driving it with the CLI

```sh
DESC="$RUN_ROOT/plugins/acme/model100/src/benchweave_acme_model100/descriptor.json"
uv run --no-sync benchweave-sdk check "$DESC"
```

Expected end state:

- exit 0, stdout `Descriptor schema and basic S01/S02/S04 checks passed; full conformance
  and hardware evidence remain separate.`
- no files written — `check` is read-only, so `tree.txt` before and after must match

Refusal arm, proving the gate is live rather than advisory:

```sh
uv run --no-sync benchweave-sdk check "$RUN_ROOT/nope.json"   # exit 1
```

A malformed descriptor is proven the same way: copy the generated one, break a required
field, and require exit 1 with the descriptor-validation error. Do not assert the prose.

## Gotchas

- **`check` is not full conformance.** It is the descriptor schema plus basic S01/S02/S04
  only. The S01–S18, C01–C12 and M01–M14 obligations and all hardware evidence are recorded
  by the author and are outside this command's coverage. A green `check` must never be
  reported as "conformant".
- **Paths must be canonical.** `check` refuses a symlinked component with
  `path_symlink_component:` — on macOS `/tmp/...` fails where `/private/tmp/...` passes.
- **A missing file surfaces as a raw `[Errno 2]`**, not a `snake_case:` prefix, because the
  read fails before the schema lane. Treat exit 1 plus `No such file or directory` as a
  path mistake, not a conformance failure.
- The generated descriptor is explicitly synthetic. A passing check on it proves the lane
  works, not that any device protocol is correct.
