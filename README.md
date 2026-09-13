# BenchWeave plugin developer SDK

Build an external device plugin without importing gateway internals. Python 3.13+, SDK 0.1.0, OTDP 0.3.0 and adapter API 1.1 are the initial baseline. This package is a separate wheel built alongside BenchWeave; it is not yet published to a package index.

## Five steps

1. Install the built SDK wheel in your development environment (`uv pip install path/to/benchweave_sdk-0.1.0-py3-none-any.whl`).
2. Run `benchweave-sdk new plugins/acme/model100 --package benchweave_acme_model100`. Replace `acme/model100` with your manufacturer/device name; the independent project contains `src/benchweave_acme_model100/` and `tests/`.
3. Replace the explicitly synthetic protocol with verified device behaviour, then update its descriptor. The generated AI-GUIDE.md describes the design, build, test, review and release steps.
4. Install the plugin with test dependencies, run its tests, and run `benchweave-sdk check src/benchweave_acme_model100/descriptor.json`. Record all applicable S01–S18, C01–C12 and M01–M14 obligations and evidence; basic SDK checks do not cover all of them.
5. Build with `uv build`, prepare registry metadata and reviewed evidence, and approve the release before publication or hardware qualification. `benchweave-sdk inventory` helps generate hashes, not a complete registry manifest.

The generated runtime has no dependency on this SDK. Its test extra pins the SDK version; while unpublished, install the built SDK wheel explicitly before resolving that extra. Generate and retain a plugin dependency lock in its repository. A template is not qualified firmware or a real instrument driver.

## Optional plugin pages and presets

Add `--with-ui` to `benchweave-sdk new` to generate a declarative readings page, presentation envelope and binding catalogue. The default scaffold stays unchanged. Keep presentation assets under the import package's `ui/` directory so wheels carry them; store complete configuration presets alongside their settings schema. Plugins can declare configuration, readings, dataset and registered panel pages, with plots only when appropriate.

Use `benchweave-sdk check-ui` and `benchweave-sdk check-preset` for offline validation before packaging. Validation neither admits a plugin nor approves applying settings. The [plugin presentation guide](../../docs/plugin-ui-v0.1.0/README.md) covers the directory structure, preconfigured settings, optional graphs, data bindings and CLI examples. These contracts prepare presentation metadata; a browser renderer and profile-action execution remain separate work.

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
