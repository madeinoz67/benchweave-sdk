# 0001. Run scripted FTDI scaffold tests with the plain SDK pin

- **Status:** Accepted
- **Date:** 2026-11-28
- **Issue:** [BenchWeave #597](https://github.com/madeinoz67/benchweave/issues/597)
- **Deciders:** Architect (proposal), Stephen Eaton (approval)

## Context

The generated provider tests supply a scripted driver to `ftdi_plugin_session` (`template/tests/test_plugin.py.jinja`). Its connection factory calls `verify_ftdi_plugin`, which checks the plugin contract before calling `_require_backend()` (`src/benchweave_sdk_server/ftdi.py`). This pulls pyftdi into a test that supplies its own driver. The template pins `benchweave-sdk[server]`, which also installs the web stack. SDK CI treats the stripped-pin provider suite as an expected failure (`.github/workflows/ci.yml`, generated-workflow A7 step).

## Decision

Extract contract-only validation into a private helper. Use it on the injected-driver connection path. Keep the existing live verifier and its preflight. Update the scaffold, fixture output, and SDK CI together so the candidate wheel proves the plain-pin provider path.

| Option | Consequence |
| --- | --- |
| Private contract helper | Reuses all validation and keeps the live verifier's API and refusal semantics. |
| Backend-skip flag on the shared verifier | Smaller edit that exposes a live-preflight bypass to shared callers. |
| Keep the pin | Preserves the existing CI control and carries the web stack into scripted tests. |

## Contracts

- Preserve `verify_ftdi_plugin(plugin: LoadedPlugin) -> FtdiContract`. CLI serve, discovery and default-driver connections keep contract validation before the backend preflight. Missing or broken backend imports retain the `RuntimeError` prefix `live_provider_backend_missing:` and the `benchweave-sdk[server]` install hint.
- The private validator takes a `LoadedPlugin` and returns the same `FtdiContract`, with the same pin, feature, grammar, limits and executor checks. Injected-driver connections validate the current `session.plugin` on every connection before resolving the endpoint or calling the factory. Use the same explicit factory-presence check for opener selection, validation and the rehearsal marker.
- Render `benchweave-sdk=={{ sdk_version }}` in the provider test extra. Base and UI keep their current test extras. Generated CI continues to use `uv sync --extra test`.

## Implementation and acceptance

| Task | Files | Proof | Dependency |
| --- | --- | --- | --- |
| T1. Split contract validation at the scripted connection boundary | `src/benchweave_sdk_server/ftdi.py`, `tests/server/test_ftdi.py` | AC-1 and AC-4. A scripted connection succeeds with a backend probe that fails the test on invocation. Invalid input refuses before driver open. The live default path preserves the prefixed refusal and install hint when the backend is missing. Verify reconnect rechecks the current plugin contract. | None |
| T2. Narrow the scaffold pin and regenerate all arms | `template/pyproject.toml.jinja`, `tests/fixtures/scaffold_expected/` | AC-2 and AC-3. All three regenerated arms pass fixture agreement. Compare generated workflow bytes and the serial test extra against the parent commit. | T1 for end-to-end verification |
| T3. Replace the retired SDK CI control | `.github/workflows/ci.yml` | AC-1. Use the regular generated provider leg as the positive plain-pin check. Assert the exact plain SDK requirement, wheel provenance and absence of pyftdi in the isolated test environment. Run all three generated lint and test legs and preserve the test count floors. | T1 and T2 for end-to-end verification |

T2 and T3 touch disjoint files and can be prepared in parallel. Land all tasks together because the current expected-failure control turns red when the plain-pin run succeeds. Exercise the candidate wheel in SDK CI even when its version also exists on the package index. Release the scaffold change with an SDK version whose wheel contains T1.

## Stability boundaries

Preserve the generated workflow bytes, serial test extra, live open and discovery behavior, device and contract validation, and public extras. This decision applies to the SDK repository. It adds no dependencies, schema, configuration, or migration.

## Consequences and rollback

Scripted provider tests no longer require the hardware backend or the server extra. The live backend stays a deployment requirement. Revert the implementation PR as a unit to restore the old template, fixtures, backend check and expected-failure control together.
