# presentation

Everything about a plugin's read-only UI: the artifacts stamped into the project, the
offline validators, and the standalone preview host.

## Sub-features

- **`verify-ui <project>`** — renders the project's class-reference presentation and
  asserts the class expectation. A render gate, not an approval.
- **`check-ui <envelope> --descriptor --resources --catalogue`** — validates one
  presentation envelope (`presentation.json`) offline.
- **`check-preset <preset> --descriptor --settings-schema`** — validates complete settings
  offline; `--firmware` is required only where the policy makes firmware decidable.
- **`derive-ui <project> [--force]`** — derives the class-reference presentation set into a
  plugin project.
- **`migrate-ui <envelope>`** — re-stamps plugin-ui contract artifacts to this SDK's active
  version. Validates before it writes, so a refusal writes nothing.
- **`preview-ui <project>`** — serves the plugin on the standalone host, transport pinned
  to the scripted mock. Needs the `[server]` extra.

## How to get to it (user POV)

Scaffold with `--with-ui`, then `cd` into the project. `verify-ui .` is the render gate a
plugin author runs before shipping. `preview-ui .` opens the same pages the standalone host
serves, so an author can look at the plugin before installing it anywhere.

## Driving it with the CLI

```sh
# the render gate
uv run --no-sync benchweave-sdk verify-ui "$RUN_ROOT/plugins/acme/ui100"

# one envelope, offline
P="$RUN_ROOT/plugins/acme/ui100/src/benchweave_acme_ui100"
uv run --no-sync benchweave-sdk check-ui "$P/presentation.json" \
  --descriptor "$P/descriptor.json" \
  --resources "$P" \
  --catalogue "$P/binding-catalogue.json"
```

Expected end state:

- `verify-ui` exit 0, stdout `Rendered gate clean; not admission, qualification or approval
  to apply settings.`
- `check-ui` exit 0, and `tree.txt` unchanged — a validator writes nothing.
- A `--with-ui` package tree contains `presentation.json`, `ui/` and
  `binding-catalogue.json`; a bare scaffold does not.

Preview, when the `[server]` extra is installed:

```sh
uv run --extra server benchweave-sdk preview-ui "$RUN_ROOT/plugins/acme/ui100" \
  --port 18477 --no-open &
PID=$!
# drive it, capture a response, then:
kill "$PID"
```

## Gotchas

- **`preview-ui` refuses on a default install** with `benchweave_sdk_server_extras_missing:`
  and exit 2 — that is the documented behaviour, not a bug. Install with
  `uv run --extra server ...` or `pip install 'benchweave-sdk[server]'`.
- **Preview binds `127.0.0.1:8477` by default.** Two parallel runs collide on the port;
  give each run its own `--port` and record the PID for cleanup. Never `pkill` by name.
- **The preview is mock-only.** `preview-ui` pins the scripted mock transport and never
  leaves it. Real hardware is `benchweave-sdk-server serve --transport serial`.
- **`[server]` pins `benchweave-ui-html` exactly**, by design. A version mismatch between
  the host's renderer and the corpus is a pin-bump, never a range widening.
- **A refused `migrate-ui` writes nothing** (`migrate_ui_ahead:`,
  `migrate_ui_version_absent:`, `migrate_ui_stamp_unlocatable:`,
  `migrate_ui_invalid_after_stamp:`). Prove that by comparing `tree.txt` before and after a
  deliberate refusal.
- `verify-ui` cleans a render; it is not admission, qualification or approval to apply
  settings. Report it as the gate it is.
