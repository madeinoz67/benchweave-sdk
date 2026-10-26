# Optional plugin presentation

The starter declares read-only observations. It adds no device actions.
The project root contains pyproject.toml, AI-GUIDE.md, this guide and tests/.
Its Python package is src/example_plugin/. Presentation files are laid out as:

```text
src/example_plugin/
  descriptor.json
  presentation.json
  binding-catalogue.json
  ui/
    manifest.json
    fixtures/  # generated synthetic preview examples
    settings/  # author-supplied schemas, when configuration exists
    presets/   # author-supplied complete configurations
    assets/    # author-supplied declared static resources
```

The SDK generates ui/manifest.json and schema-valid examples in ui/fixtures/.
Run `benchweave-sdk regen-fixtures <project>` to write the two examples
again after you edit the binding catalogue.
Add settings/ and presets/ only for configuration actions the descriptor implements.
Keep resources inside the Python package so they ship in the wheel.
Keep collected data, credentials and deployment configuration outside it.

Run from the project root: `benchweave-sdk check-ui src/example_plugin/presentation.json --descriptor src/example_plugin/descriptor.json --resources src/example_plugin --catalogue src/example_plugin/binding-catalogue.json`.
When a new SDK release moves the active plugin-ui version,
`benchweave-sdk migrate-ui` re-stamps the three presentation documents and
takes the same arguments as check-ui.

--resources names the package root; the envelope selects resource_root=ui.
Manifest asset paths are relative to ui/, for example presets/default.json.
Use canonical paths without symlink components. Keep the binding catalogue
aligned with the descriptor and update exact byte hashes after edits.

A manifest `assets[]` row whose `path` is exactly `preview.css` restyles
the preview pages. Put the file at
`src/example_plugin/ui/preview.css`, beside ui/manifest.json. The row
path is relative to ui/, the resource root. Do not put the file
under ui/assets/. The row also declares the `sha256` digest of the
file bytes, and the host checks the digest again at serve time. The
file can be 64 KiB at most. The override serves on the standalone
host only, and the gateway never serves a plugin stylesheet
override. A refused override gives the prefix
`standalone_preview_override_refused:`, and the page carries the
marker `data-bw-override-refused` while the default tokens render.
The user guide covers the override in
section "The plugin stylesheet override (preview.css)".

When the device has features the class reference does not place,
decide each one. The reference places the member: do nothing. The
device adds a few vendor features: compose them. Author a composed
action class for the catalog side of an action, or a composed
member declaration for the slot and its page. Put the document
beside descriptor.json and pin it under `contracts[]` with the
sha256 of the file bytes; the document and its pin move together.
Nothing covers the member: leave it as a residual member. The
derivation does not refuse. It derives the `Custom device actions`
section, and the gate reports the member on every run. The user
guide gives the document shapes in
section "Author a composed action class" and
section "Author a composed member declaration".

Preview with: `benchweave-sdk preview-ui .` from the project root (the standalone host on the scripted mock transport; needs the `benchweave-sdk[server]` extra).

All preview values and receipts are simulated. check-ui and preview-ui are not
admission, hardware qualification or permission to operate hardware.
Declared manifest plots and channel hints render in the preview; plot values
are per-scenario snapshots (one simulated value per observed target), not history.
A descriptor with no numeric observation target ships no example plot.
Preset selection performs no I/O. Applying settings requires a separately
approved procedure. Acquisition and retained observations belong to the gateway.
