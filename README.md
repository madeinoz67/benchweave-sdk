# BenchWeave plugin developer SDK

Build an external device plugin without importing gateway internals. Python 3.13+, SDK 0.1.0, OTDP 0.3.0 and adapter API 1.1 are the initial baseline. This package is a separate wheel built alongside BenchWeave; it is not yet published to a package index.

## Five steps

1. Install the built SDK wheel in your development environment (`uv pip install path/to/benchweave_sdk-0.1.0-py3-none-any.whl`).
2. Run `benchweave-sdk new plugins/acme/model100 --package benchweave_acme_model100`. Replace `acme/model100` with your manufacturer/device name; the independent project contains `src/benchweave_acme_model100/` and `tests/`.
3. Change into the generated project (`cd plugins/acme/model100`). Replace the explicitly synthetic protocol with verified device behaviour, then update its descriptor. The generated AI-GUIDE.md describes the design, build, test, review and release steps.
4. Install the plugin with test dependencies, run its tests, and run `benchweave-sdk check src/benchweave_acme_model100/descriptor.json`. Record all applicable S01–S18, C01–C12 and M01–M14 obligations and evidence; basic SDK checks do not cover all of them.
5. Build with `uv build`, prepare registry metadata and reviewed evidence, and approve the release before publication or hardware qualification. `benchweave-sdk inventory` helps generate hashes, not a complete registry manifest.

The generated runtime has no dependency on this SDK. Its test extra pins the SDK version; while unpublished, install the built SDK wheel explicitly before resolving that extra. Generate and retain a plugin dependency lock in its repository. A template is not qualified firmware or a real instrument driver.

## Directory structure

In a plugin collection, each device plugin is an independent project at `plugins/<manufacturer>/<name>/`. The SDK itself stays in `packages/sdk/`. An external plugin repository can use that device project as its repository root; it does not need the enclosing `plugins/<manufacturer>/` directories. The project directory and Python import package have different roles: `acme/model100` organises the collection, while `benchweave_acme_model100` is the import name selected by `--package`.

Create a project from the collection root:

```sh
benchweave-sdk new plugins/acme/model100 --package benchweave_acme_model100 --with-ui
cd plugins/acme/model100
```

The destination must not already exist. Omit `--with-ui` for a plugin without presentation metadata.

```text
plugins/acme/model100/                 # independent plugin project
├── pyproject.toml                     # build configuration and test dependencies
├── README.md
├── AI-GUIDE.md                        # generated development workflow
├── UI-GUIDE.md                        # generated only with --with-ui
├── docs/                              # author-supplied device documentation
│   ├── compatibility.md               # supported models/firmware and limitations
│   └── qualification.md               # supervised hardware test plan/evidence
├── firmware/                          # optional author-supplied firmware material
│   ├── README.md                      # official sources, versions and checksums
│   └── release-notes/                 # relevant vendor changes and upgrade constraints
├── src/
│   └── benchweave_acme_model100/       # import package; included in the wheel
│       ├── __init__.py
│       ├── adapter.py                 # SDK-facing adapter and create_plugin
│       ├── protocol.py                # device protocol implementation
│       ├── descriptor.json            # OTDP device/operation contract
│       ├── protocol.md                # protocol evidence, initially synthetic
│       ├── vectors.json               # exact exchanges, initially synthetic
│       ├── config/                    # optional configuration for a headless plugin
│       │   ├── settings.schema.json   # author-supplied complete-settings schema
│       │   └── presets/
│       │       └── default.json       # author-supplied configuration preset
│       ├── presentation.json          # --with-ui: envelope and resource root
│       ├── binding-catalogue.json     # --with-ui: descriptor-aligned targets
│       └── ui/                        # --with-ui: presentation resource root
│           ├── manifest.json          # generated readings page; no plot required
│           ├── fixtures/              # generated synthetic preview examples
│           │   ├── normal.json
│           │   └── warning.json
│           ├── settings/              # author-supplied, when configuration exists
│           │   └── settings.schema.json
│           ├── presets/               # author-supplied complete configurations
│           │   └── default.json
│           └── assets/                # author-supplied declared static resources
└── tests/
    ├── test_plugin.py                 # generated mock/conformance tests
    ├── test_presentation_preview.py   # generated offline preview conformance test
    ├── test_configuration.py          # author-supplied schema/preset checks
    ├── test_presentation.py           # author-supplied UI binding/asset checks
    └── fixtures/                      # author-supplied exchanges by model/firmware
```

The SDK generates `ui/manifest.json`, schema-valid synthetic examples under `ui/fixtures/`, and `tests/test_presentation_preview.py`. The `docs/`, `firmware/`, `config/`, optional UI asset directories and additional test files remain author-supplied extensions. Add only the features the device plugin supports. `default.json` is an example filename, not an automatically selected or applied configuration.

| Optional feature | Recommended location | Behaviour and ownership |
| --- | --- | --- |
| Device configuration without UI | `src/<package>/config/settings.schema.json` and `config/presets/` | Validate complete settings offline with `check-preset`; application requires an approved device procedure. |
| Device configuration shown in UI | `src/<package>/ui/settings/` and `ui/presets/` | Keep one authoritative copy inside the UI resource root and declare it in the manifest; do not duplicate it under `config/`. |
| Specialised pages and optional graphs | `src/<package>/ui/manifest.json` and `ui/assets/` | Declare bindings, plot metadata and supported panel IDs. A page need not have a graph. Browser rendering remains separate work. |
| Data collection | Descriptor action/measurement contracts, adapter code and `tests/fixtures/` | Declare supported acquisition and dataset bindings. The gateway owns execution and retained data; live datasets are not packaged here. |
| Firmware compatibility | `docs/compatibility.md`, descriptor firmware constraints and firmware-specific test fixtures | State supported firmware versions and retain evidence. The descriptor remains the runtime compatibility contract. |
| Firmware reference material | `firmware/README.md` and `firmware/release-notes/` | Record vendor sources, exact version/checksum information and upgrade constraints. This directory has no SDK discovery or flashing behaviour. Redistribute vendor images only when permitted and explicitly required by the release. |
| Hardware qualification | `docs/qualification.md` | Record the supervised test plan, tested versions and evidence. Synthetic tests do not establish hardware qualification. |

A preset contains complete settings and compatibility/provenance metadata, not collected measurements. A plugin can have configuration without UI, UI without configuration, and firmware compatibility declarations without shipping firmware images.

Keep distributable resources inside `src/<package>/` so the generated Hatch wheel configuration includes them. Generate and retain `uv.lock` for development dependencies, and supply the appropriate licence and release evidence before distribution; these are not scaffolded. Build outputs belong in `dist/`. Gateway configuration, credentials, live readings and retained datasets belong to the deployment/runtime stores, outside the plugin source package.

### Path resolution and validation

Run these commands from the plugin project root after installing its development dependencies:

```sh
benchweave-sdk check src/benchweave_acme_model100/descriptor.json
benchweave-sdk check-ui src/benchweave_acme_model100/presentation.json \
  --descriptor src/benchweave_acme_model100/descriptor.json \
  --resources src/benchweave_acme_model100 \
  --catalogue src/benchweave_acme_model100/binding-catalogue.json \
  --firmware 1.0.0
pytest
uv build
```

Here `--resources` points to the **package root**. The generated envelope's `resource_root: "ui"` selects its `ui/` subdirectory. Manifest asset paths such as `settings/settings.schema.json` and `presets/default.json` are relative to that UI root. Resource paths must remain inside the root and cannot traverse symlinks; use canonical local paths. On macOS, use `/private/tmp/...` rather than the `/tmp` symlink for temporary preview projects. Keep descriptor, manifest and asset byte hashes current after editing resources. The binding catalogue must be aligned with the descriptor and verified by the host during admission; a packaged candidate catalogue does not grant device capabilities.

## Optional plugin pages and presets

Add `--with-ui` to `benchweave-sdk new` to generate a declarative readings page, presentation envelope and binding catalogue. The default scaffold stays unchanged. Keep presentation assets under the import package's `ui/` directory so wheels carry them; store complete configuration presets alongside their settings schema. Plugins can declare configuration, readings, dataset and registered panel pages, with plots only when appropriate.

Use `benchweave-sdk check-ui` and `benchweave-sdk check-preset` for offline validation before packaging. Validation neither admits a plugin nor approves applying settings. The [plugin presentation guide](../../docs/plugin-ui-v0.1.0/README.md) covers the directory structure, preconfigured settings, optional graphs, data bindings and CLI examples.

### Local UI preview

The SDK includes the version-matched React renderer and nine deterministic baseline scenarios. Preview author fixtures without importing plugin Python, opening a device transport or contacting a gateway:

```sh
benchweave-sdk preview-ui src/benchweave_acme_model100/presentation.json \
  --descriptor src/benchweave_acme_model100/descriptor.json \
  --resources src/benchweave_acme_model100 \
  --catalogue src/benchweave_acme_model100/binding-catalogue.json \
  --fixtures src/benchweave_acme_model100/ui/fixtures
```

Use `--no-open` for CI or a terminal-only readiness check. The default listener is an ephemeral port on `127.0.0.1`; wildcard listeners are rejected. A non-loopback host requires `--allow-network` and remains unsuitable for shared or production deployment. UI contributors can point at a compatible Vite renderer with `--renderer-url`; both renderers require preview API version 1.

Every preview is labelled `SIMULATED PRESENTATION DATA`. Control interactions create only in-memory simulated receipts and never update observed readings optimistically. Preview success is not admission, hardware qualification or permission to operate equipment.

## Public surfaces

- `interfaces`: structural async `Adapter`, `HostServices`, `OperationContext` and optional `CaptureServices` definitions. No SDK superclass is required.
- `testing`: deterministic `MockContext` and `MockHost`, exact scripted transfers, dispatch markers, cancellation and a manually advanced clock. These are test doubles, not qualified host services.
- `validation`: pinned local schemas, strict finite JSON, format validation, runtime correlation and basic descriptor S01/S02 checks. Unresolved schema references fail without network retrieval.
- `conformance`: reusable operation and quiet lifecycle checks, with configurable wall-clock timeouts for cooperative async calls. Authors must add device-specific failure, profile and measurement tests. Use process isolation for blocking code or code that suppresses cancellation.
- `presentation`: bounded offline validation of presentation resources and complete configuration presets, using the same validator bytes as the gateway.
- `packaging`: inventory and integrity checks for a prepared bundle, including duplicate/path/symlink rejection. No installation, signing, publication or dependency execution.

## Compatibility and limits

The gateway has an explicit OTDP bridge and loader for identify, scalar read and scalar write. Profile actions, capture and streaming are not implemented by that bridge. Package-relative and standard-library imports are supported; arbitrary third-party runtime dependencies need further integration. Existing simulator interfaces remain private. Release CI builds an SDK and external plugin outside the checkout and exercises that plugin through the gateway bridge using mock transport. Unsupported operations must fail explicitly. No live install endpoint, physical backend, container device permissions or hardware qualification is supplied by this SDK.

The SDK sdist and wheel include the canonical OTDP, registry and plugin presentation contract sets. Build from the repository with `uv build packages/sdk`; the build hook includes contract resources and a wheel rebuilt from the sdist remains self-contained. The release smoke compares installed contract bytes with the canonical repository copies. SDK and gateway versions are independently named; each release must record the exact pair tested before expanding compatibility claims.

Pure Python plugins still need declared dependencies and compatible runtimes. Native dependencies and physical transport mappings require a separately qualified gateway deployment. The SDK does not install dependencies into a running gateway.

## Distribution rights

The existing project licence remains Proprietary. This implementation does not grant a new open-source licence for the SDK, copied contracts or templates. The project owner must establish distribution rights before public publication. Generated examples deliberately contain no invented licence grant; choose the appropriate plugin licence and provide its file before release.
