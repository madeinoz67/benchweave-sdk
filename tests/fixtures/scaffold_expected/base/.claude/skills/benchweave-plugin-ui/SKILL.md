---
name: benchweave-plugin-ui
description: Use when you validate or preview plugin UI presentation —
  check-ui, check-preset and preview-ui runs for presets, manifests
  and fixtures.
---

# Plugin UI checks and preview

The commands work offline. None of them contacts a gateway, the registry
or hardware.

## Derive the presentation set

A class-conformant descriptor derives its presentation set. Derive the set
with `derive-ui` before you write pages by hand. The `new --with-ui` scaffold
derives the set already.

The derivation shows the `cannot_derive` items. The items name what the
derivation cannot decide. You decide them as the author. The AI-GUIDE names
the items and the author actions. Verify the derived set with `verify-ui`.

## Validate a presentation candidate

- `benchweave-sdk check-ui <envelope.json> --descriptor <descriptor.json>
  --resources <resource-root> --catalogue <binding-catalogue.json>` — validate
  one presentation candidate offline. Optional flags: `--firmware`, repeatable
  `--feature`, repeatable `--panel`.

## Validate a complete preset

- `benchweave-sdk check-preset <preset.json> --descriptor <descriptor.json>
  --settings-schema <settings.schema.json>` — validate one complete settings
  file offline. Optional flag: `--firmware`. Omit it to validate structurally
  under a commissioned descriptor; under the listed policy the check needs a
  firmware value to judge compatibility. `--action` forces the action whose
  envelope is applied.

## Preview simulated states

- `benchweave-sdk preview-ui <project>` — serve the project's pages on the
  standalone host, on the scripted mock transport. The command needs the
  server extra: install `benchweave-sdk[server]`. Extra flags: `--host`,
  `--port`, `--allow-network`, `--no-open`, `--scenario <id>`. Real hardware
  is served by `benchweave-sdk-server serve --transport serial`; preview-ui
  never leaves the mock transport.

## Restyle the preview pages (optional)

A manifest `assets[]` row with `path` exactly `preview.css` restyles the
preview pages. The row also declares the `sha256` digest of the file bytes,
and the host checks the digest again at serve time. The file can be 64 KiB
at most. The override serves on the standalone host only, and the gateway
never serves a plugin stylesheet override. A refused override gives
`standalone_preview_override_refused:` while the page renders the default
tokens. The plugin SDK guide covers this in
section "The plugin stylesheet override (preview.css)".

## Refresh the example fixtures

The scaffold writes two example fixtures into `ui/fixtures/`. The examples
track the binding catalogue. Run `benchweave-sdk regen-fixtures <project>`
after you edit the binding catalogue. Run it also after a plugin-ui-preview
version bump. The command refuses to overwrite a file whose scenario id is
not `example-normal` or `example-warning`. The command never touches author
scenarios at their own ids.

## Rules that bite

- The preview listener uses loopback only. A non-loopback host needs
  `--allow-network`.
- Input paths that contain a symlinked component are refused. Use canonical
  paths.
- Every scenario, observation and control receipt in the preview is simulated
  data, labelled as such. The preview path has no gateway, registry or hardware
  reach.
- A clean preview is not an admission. A clean check is not an approval to
  apply settings.

## Read the docs

The plugin SDK guide covers this in section "Local UI preview (simulated)".

---
Maintained by benchweave-sdk 0.21.0; `benchweave-sdk upgrade`
refreshes this skill.
