# Plugin developer SDK

The SDK gives you a small starting point for developing a BenchWeave device plugin with AI: **generate → implement → test → review → prepare a release**. Use this guide for SDK installation, project generation, testing and packaging. The [device developer guide](https://github.com/madeinoz67/benchweave/blob/main/docs/device-developer-guide.md) (main repository) covers device evidence, integration requirements, firmware and qualification.

The device is the hardware; the plugin is its Python integration and descriptor. Follow the [developer directory convention](https://github.com/madeinoz67/benchweave/blob/main/docs/device-developer-guide.md#repository-layout-for-device-plugins): `plugins/<manufacturer>/<name>/`, with `src/<python_package>/` inside that project. The name normally identifies the device model, such as `fnirsi/dps150`.

The first SDK is `benchweave-sdk` 0.0.2 for Python 3.13+, OTDP 0.3.0 and adapter API 1.1, with registry 1.0.0 schemas. Its source lives in this repository, mounted at `packages/sdk` in the [main BenchWeave repository](https://github.com/madeinoz67/benchweave), and is built separately from the gateway. It supplies structural typing interfaces, offline contract validation, a scripted mock host, bounded async conformance helpers, an external project generator and file-inventory helpers.

## 1. Install the SDK and generate your project

Install the SDK from PyPI:

```sh
pip install benchweave-sdk
# or as an isolated CLI tool
uv tool install benchweave-sdk
```

For bleeding-edge work before a release, install straight from the default branch:

```sh
pip install git+https://github.com/madeinoz67/benchweave-sdk.git
```

Full channel list: see the README Installation section.

PyPI is the default install channel: `pip install benchweave-sdk` or `uv pip install benchweave-sdk`. Contributors and maintainers can instead build from a checkout of the main BenchWeave repository — run this from that checkout's root; `packages/sdk` is the submodule mount path there, not a directory in this repository:

```sh
uv build packages/sdk --out-dir dist/sdk
```

In your development directory, create an environment and install the built wheel from the checkout's `dist/sdk/`:

```sh
uv venv --python 3.13
source .venv/bin/activate
uv pip install dist/sdk/benchweave_sdk-0.0.2-py3-none-any.whl
benchweave-sdk new plugins/acme/model100 --package benchweave_acme_model100
cd plugins/acme/model100
uv pip install -e '.[test]'
pytest
```

Keep using the environment containing the SDK wheel; if you create a new environment inside the project, install the wheel there too. For a repeatable `uv lock` against a locally built wheel, configure that wheel or your organisation's package source explicitly.

Replace `acme/model100` with your manufacturer and device/plugin name. The destination controls the directory hierarchy; `--package` controls the Python import package. The SDK creates missing parent directories and refuses to overwrite an existing project.

```text
plugins/
└── acme/
    └── model100/                       # Independent build/test/release root
        ├── pyproject.toml
        ├── README.md
        ├── AI-GUIDE.md
        ├── src/benchweave_acme_model100/
        │   ├── __init__.py
        │   ├── adapter.py
        │   ├── protocol.py
        │   ├── descriptor.json
        │   ├── protocol.md
        │   └── vectors.json
        └── tests/test_plugin.py
```

Generate and retain the dependency lock, add your chosen licence file, and add `firmware/` with its own build/tests when developing custom firmware. These project-specific files are not invented by the starter. The manufacturer/name directory can be copied into its own external repository unchanged; it has no runtime dependency on BenchWeave core or the SDK. The SDK is a development dependency.

The starter deliberately implements a made-up, read-only identify/voltage protocol. Passing its tests demonstrates that the tools work; it says nothing about your instrument.

## 2. Give the AI the facts and prompts

Open the generated **`AI-GUIDE.md`**. It contains five copyable prompts: establish device facts, implement with mocks, demonstrate behaviour, prepare independent review, and prepare release artefacts for owner review.

Provide the exact model, firmware, transport, supported operations and authoritative protocol evidence. Review the AI's proposed scope before replacing the example. It should keep protocol parsing separate from the async adapter and use only supplied scoped host services. The current gateway loader supports package-relative and standard-library imports; arbitrary third-party runtime dependencies need additional integration work.

For custom hardware, follow [Build my own device firmware](https://github.com/madeinoz67/benchweave/blob/main/docs/develop-your-device.md) (main repository) as well. Firmware and the Python plugin have separate builds and compatibility evidence, even when maintained in one project.

## 3. Run the checks

From your plugin project, using the environment containing the SDK:

```sh
pytest
benchweave-sdk check src/benchweave_acme_model100/descriptor.json
uv build
```

Generated tests cover identify/read, quiet lifecycle, invalid inputs, pre-dispatch cancellation/expiry and uncertain malformed/transport responses. Extend them for your actual operations, failure modes and evidence. `check_operation` validates request/result schemas and correlation. `check_lifecycle` checks a quiet lifecycle and repeated cleanup. Both bound cooperative async calls with a configurable wall-clock timeout; blocking Python or code that suppresses cancellation needs process-level isolation.

Descriptor checks currently cover its schema, matching capabilities/policies, unique parameter names and ordered ranges. These are **partial checks**, not all S01–S18, C01–C12 or M01–M14 obligations. The SDK provides no physical transport provider, complete profile/capture test harness or hardware qualification certificate.

## Local UI preview (simulated)

`benchweave-sdk check-ui`, `check-preset` and `preview-ui` validate presentation candidates and preview them offline. `preview-ui` serves the versioned preview API and the bundled React renderer on loopback only; every scenario, observation and control receipt is simulated and labelled as such — the preview path has no gateway, registry or hardware reach. An external development renderer (`--renderer-url`, e.g. a local Vite dev server) must also name a loopback host; non-loopback renderer origins are rejected because plugin authors can suggest command lines. The served document's shape is pinned by [plugin-ui-preview-v1](https://github.com/madeinoz67/benchweave/blob/main/standards/plugin-ui-preview-v1/preview-document.schema.json) (main repository), validated from both the Python emitter and the renderer's decoder.

The SDK's runtime dependencies are Click, jsonschema (+ referencing, rfc3339-validator, rfc3987 format backends), Rich and Textual — all declared in this repository's `pyproject.toml` (the file at `packages/sdk/pyproject.toml` in a main-checkout layout); the wheel vendors the canonical contract JSONs, the pure presentation validator and the built renderer assets.

Operational notes: `preview-ui` is an interactive tool — with output redirected (or `--no-open`) it serves until interrupted by design, exiting 0 on SIGINT as a normal stop; a fixed `--port` can hit a short `EADDRINUSE` window on immediate restart (deliberate anti-port-steal posture — prefer the default ephemeral port); request bodies have no handler timeout, which only matters for untrusted peers under the explicitly acknowledged `--allow-network` mode.

## 4. Review compatibility and deployment

Use the [AI device integration reviewer](https://github.com/madeinoz67/benchweave/blob/main/docs/ai-device-reviewer.md) (main repository) with the exact revision and test evidence. Its SDK maintenance checklist covers public interfaces, contracts, generated projects, mocks, gateway compatibility and release artefacts.

The gateway now has an explicit `load_otdp_plugin`/`OTDPBridge` path for async adapter API 1.1. Its supported host operations are **identify, scalar read and scalar write**. The release smoke exercises a generated multi-module plugin through identify/read; separate bridge tests cover write conversion and rejection paths. Profile actions, capture and streaming remain unsupported by this bridge. The existing simulator loader is retained for its separate synchronous interface.

A gateway integrator must first complete admission, supply the verified manifest/cache and descriptor, inject authorised scoped services, and use the same monotonic timebase as the host's deadlines. The loader rechecks all listed file hashes and imports verified package code/resources in memory. This is integrity checking and namespace isolation, not an operating-system sandbox. Adapters remain trusted Python.

An SDK install does **not** add a plugin to a running workbench. There is no live device-install endpoint, automatic dependency installer or Docker hot-install command. A Docker deployment still needs persistent verified package storage, bench configuration, commissioned host services and activation at an approved idle boundary. See [package formats and gateway installation](https://github.com/madeinoz67/benchweave/blob/main/docs/develop-your-device.md#package-format-and-gateway-installation) (main repository).

## 5. Prepare the release, then approve publication

A Python wheel/source distribution and a registry release are different artefacts. Prepare the registry-required identity, exact compatibility, payload inventory, hashes, dependency locks, licence, source/build provenance, SBOM and evidence status. `benchweave-sdk inventory <prepared-bundle-directory>` prints file paths, byte counts and SHA-256 values; it does not create or approve a complete registry manifest.

Show the owner the actual built files, evidence and remaining gaps before publishing. Hardware qualification and local commissioning remain separate. The SDK retains the project's proprietary licence declaration; release owners must establish distribution rights before sharing it publicly.

## Maintenance and release cycle

The main repository's Package workflow builds the gateway and SDK from source distributions, then tests installed wheels in temporary environments on Linux and macOS. It generates, builds and installs an external plugin outside the checkout, runs its tests, checks packaged contract bytes and versions, exercises gateway loading and rejects tampered code.

Run the same check locally from a checkout of the main BenchWeave repository (`scripts/sdk_smoke.py` lives there, not in this repository):

```sh
uv run --no-project --python 3.13 scripts/sdk_smoke.py --out-dir dist/packages
```

On a published GitHub release, a separate job repeats these checks before attaching the SDK wheel and source distribution to that release. Tagging a release triggers the publish workflow, which builds the sdist and wheel, smoke-installs the wheel on four OS/arch lanes, and publishes to PyPI via Trusted Publishing. No release is published simply by editing these files or running the local smoke check.

When changing the SDK API, canonical contracts, template, gateway bridge or build tooling, update the affected tests and documentation together. Keep SDK distribution metadata, `__version__`, generated development dependency and this compatibility statement aligned; the smoke checks guard the installed distribution and contract resources.
