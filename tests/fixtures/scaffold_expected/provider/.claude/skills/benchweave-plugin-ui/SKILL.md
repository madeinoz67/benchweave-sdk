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
with `derive-ui` before you extend it. The `new --with-ui` scaffold derives
the set already.

The derivation shows the `cannot_derive` items. The items name what the
derivation cannot decide. You decide them as the author. The AI-GUIDE names
the items and the author actions. Verify the derived set with `verify-ui`.

## Vendor customizations

The class reference places the surfaces it covers. Decide the rest. Three
cases cover every member:

1. The class reference already places the member. Do nothing. The
   derivation derives the surface from the reference.
2. The device is mostly a class with a few vendor features. Compose them.
   Author a composed action class when no catalog describes an action: the
   class supplies the catalog side. Author a composed member declaration
   when the reference places no slot: the declaration supplies the slot
   and its page. Put the document in the plugin package, beside the
   descriptor. Pin it in `descriptor.json` under `contracts[]`, with the
   sha256 of the file bytes.
3. No class reference and no catalog covers the member. Leave it as a
   residual member. The derivation does not refuse. It derives the member
   into the `Custom device actions` section, and the gate reports the
   member on every run.

Each case has a cost. Case 1 costs nothing. Case 2 costs the authored
document and its pin: an edit to the document moves the bytes, so the pin
moves with them. A class or a member that names no action the descriptor
declares applies nowhere, and the gate discloses it on every run. Case 3
costs the class semantics: the custom surface renders from the descriptor
alone, apart from the catalogued surfaces, and the report row stays until
you compose the member.

The authoring contract lives in two documents. The plugin SDK guide gives
the document shapes and the pin row, in
section "Author a composed action class" and
section "Author a composed member declaration". The class reference
family README in the main repository gives the normative rule, in
`standards/plugin-ui-class-reference/`, section
`Composed member declarations (normative, gateway issue #556)`.

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
Maintained by benchweave-sdk 0.23.0; `benchweave-sdk upgrade`
refreshes this skill.
