# packaging

Turning a finished plugin into an artefact set, and hashing a prepared bundle.

## Sub-features

- **`inventory <directory>`** — prints a JSON array of `{path, bytes, sha256}` rows for the
  prepared bundle. Hashes, not a release manifest.
- **`package <plugin_dir>`** — writes the submission artefact set under `--out`, keyless by
  default; `--publisher-key` applies the publisher's own signature at package time.
- **`submit <artefact set> --registry-clone`** — writes a packaged artefact set into a
  registry clone.

## How to get to it (user POV)

An author reaches a green `check`, then runs `inventory` to get the hashes the registry
metadata cites, then `package` to produce the artefact set for a submission. Both are
offline.

## Driving it with the CLI

```sh
uv run --no-sync benchweave-sdk inventory "$RUN_ROOT/plugins/acme/model100"
```

Expected end state:

- exit 0 and a JSON array on stdout — one row per file in the tree, each with `path`,
  `bytes` and `sha256`
- parse it as JSON and assert the expected files appear (for a bare scaffold:
  `descriptor.json`, `vectors.json`, the `skills/` entries). Do not diff the whole array
  against a golden file; unrelated generated files will churn it.

`package` needs a clone of `benchweave-registry`:

```sh
uv run --no-sync benchweave-sdk package "$RUN_ROOT/plugins/acme/model100" \
  --registry-clone "$REGISTRY_CLONE" \
  --source-url <plugin source repo URL> \
  --revision <40-or-64-hex commit digest> \
  --publisher <vetted publisher id> \
  --out "$RUN_ROOT/out"
```

Without a clone the command fails while reading `<clone>/lane-rules.json`. That is a
missing precondition, not a defect in the change under test — record it as unproven rather
than as a failure.

## Gotchas

- **`inventory` is not a release manifest.** It helps generate registry metadata; the
  manifest itself is authored and reviewed.
- **`--revision` must be an immutable 40- or 64-hex commit digest.** A branch name is not a
  revision.
- **`package` is keyless by default.** Signing is the publisher's own key at package time;
  the registry validates and labels, never signs.
- **A registry clone is an external dependency.** If the run has no clone, stop at
  `inventory` and say so; do not fabricate a manifest to make the step look complete.
- `submit` writes into a registry clone — a git working tree. Point it at a disposable
  clone, never at the user's real one.
