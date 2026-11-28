# Feature map — benchweave-sdk CLI

One file per user-facing feature. Each answers, from the plugin author's point of view:
what it is, how they reach it, how to drive it, and what observable end state proves it
works.

| Feature | Entry command | Proof that it works |
|---|---|---|
| [scaffold](scaffold.md) | `new`, `doctor`, `upgrade`, `adopt` | a project tree renders, its pin matches the SDK, and a second `new` at the same path refuses |
| [descriptor-check](descriptor-check.md) | `check` | exit 0 plus the S01/S02/S04 pass line on a generated descriptor; exit 1 on a broken one |
| [presentation](presentation.md) | `verify-ui`, `check-ui`, `check-preset`, `migrate-ui`, `derive-ui`, `preview-ui` | the render gate passes; the envelope and catalogue are accepted; the preview host serves |
| [standards-sync](standards-sync.md) | `sync-standards --check` | "Standards verified (committed lock and vendored tree agree)." and exit 0 |
| [packaging](packaging.md) | `inventory`, `package` | JSON hash rows for the whole tree; an artefact set under `--out` |

A change is proved against this map when a run drives the entry point of every feature it
touches. Driving one convenient command and calling it done understates the surface.
