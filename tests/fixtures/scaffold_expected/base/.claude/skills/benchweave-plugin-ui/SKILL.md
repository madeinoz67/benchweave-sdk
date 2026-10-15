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
  --settings-schema <settings.schema.json> --firmware <version>` — validate one
  complete settings file offline. `--action` forces the action whose envelope
  is applied.

## Preview simulated states

- `benchweave-sdk preview-ui <project>` — serve the project's pages on the
  standalone host, on the scripted mock transport. The command needs the
  server extra: install `benchweave-sdk[server]`. Extra flags: `--host`,
  `--port`, `--allow-network`, `--no-open`, `--scenario <id>`. Real hardware
  is served by `benchweave-sdk-server serve --transport serial`; preview-ui
  never leaves the mock transport.

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
Maintained by benchweave-sdk 0.13.0; `benchweave-sdk upgrade`
refreshes this skill.
