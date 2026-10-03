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
Add settings/ and presets/ only for configuration actions the descriptor implements.
Keep resources inside the Python package so they ship in the wheel.
Keep collected data, credentials and deployment configuration outside it.

Run from the project root: `benchweave-sdk check-ui src/example_plugin/presentation.json --descriptor src/example_plugin/descriptor.json --resources src/example_plugin --catalogue src/example_plugin/binding-catalogue.json`.

--resources names the package root; the envelope selects resource_root=ui.
Manifest asset paths are relative to ui/, for example presets/default.json.
Use canonical paths without symlink components. Keep the binding catalogue
aligned with the descriptor and update exact byte hashes after edits.

Preview with: `benchweave-sdk preview-ui src/example_plugin/presentation.json --descriptor src/example_plugin/descriptor.json --resources src/example_plugin --catalogue src/example_plugin/binding-catalogue.json --fixtures src/example_plugin/ui/fixtures`.

All preview values and receipts are simulated. check-ui and preview-ui are not
admission, hardware qualification or permission to operate hardware.
Declared manifest plots and channel hints render in the preview; plot values
are per-scenario snapshots (one simulated value per observed target), not history.
A descriptor with no numeric observation target ships no example plot.
Preset selection performs no I/O. Applying settings requires a separately
approved procedure. Acquisition and retained observations belong to the gateway.
