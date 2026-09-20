"""Generate a standalone, read-only synthetic plugin; never contact hardware."""

from __future__ import annotations

import json
import keyword
import re
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .validation import validate_descriptor

# A generated project whose package shadows the SDK itself or a stdlib module
# breaks its own install and tests; deny those names up front.
RESERVED_PACKAGE_NAMES = frozenset({"benchweave", "benchweave_sdk"}) | frozenset(
    sys.stdlib_module_names
)

ADAPTER = '''"""Read-only synthetic OTDP adapter; qualify a real device separately."""
import math
from .protocol import transaction, parse_identity, parse_voltage


def create_plugin():
    return Plugin()


class Plugin:
    def __init__(self):
        self.services = None
        self.closed = False

    async def open(self, descriptor, services, context):
        if self.services is not None or self.closed:
            raise RuntimeError("Use a fresh plugin instance")
        self.services = services

    async def execute(self, request, context):
        verb = request.get("verb")
        operation_id = request.get("operation_id")
        dispatched = False

        def failure(code, message, uncertain=False):
            return {"operation_id": operation_id, "verb": verb,
                    "status": "unknown" if uncertain else "error",
                    "error": {"code": code, "message": message,
                              "dispatch_state": "unknown" if uncertain else "not_dispatched"}}

        def remaining():
            deadline = context.deadline_monotonic
            if (not math.isfinite(deadline) or context.is_cancelled()
                    or self.services.monotonic() >= deadline):
                raise TimeoutError("Cancelled or expired")

        if self.services is None or self.closed:
            return failure("INTERNAL_ERROR", "Plugin is not open")
        if operation_id != context.operation_id:
            return failure("INVALID_ARGUMENT", "Context identity mismatch")
        if verb not in ("identify", "read"):
            return failure("UNSUPPORTED", "Only identify and voltage read are supported")
        if (set(request) != {"operation_id", "verb", "arguments"}
                or not isinstance(operation_id, str) or not operation_id):
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        expected = {} if verb == "identify" else {"parameter": "voltage"}
        if request["arguments"] != expected:
            return failure("INVALID_ARGUMENT", "Invalid arguments")
        try:
            remaining()
            await context.mark_dispatch_started()
            dispatched = True
            response = await self.services.transfer(transaction(verb), context)
            remaining()
            if verb == "identify":
                data = parse_identity(response["data"])
            else:
                data = {"parameter": "voltage", "value": parse_voltage(response["data"]),
                        "unit": "V", "observed_at": self.services.utc_now(), "age_ms": 0,
                        "quality": "valid", "source": "device"}
            return {"operation_id": operation_id, "verb": verb, "status": "ok", "data": data}
        except TimeoutError:
            return failure("TIMEOUT", "Deadline or cancellation", dispatched)
        except ConnectionError:
            return failure("TRANSPORT_ERROR", "Connection lost", dispatched)
        except (ValueError, KeyError, TypeError):
            return failure("PROTOCOL_ERROR", "Invalid device response", dispatched)
        except RuntimeError:
            return failure("INTERNAL_ERROR", "Host resource or internal failure", dispatched)

    async def next_event(self, subscription_id, context):
        return None

    async def close(self, context):
        if self.closed:
            return
        if self.services is not None:
            await self.services.close_transport(context)
        self.closed = True
'''

PROTOCOL = '''"""Synthetic exchanges only; this is not a commercial instrument driver."""
import math


def transaction(verb):
    return {"kind": "stream_exchange", "data": b"ID?\\n" if verb == "identify" else b"V?\\n",
            "max_bytes": 128, "termination": "lf", "exact_bytes": None}


def parse_identity(raw):
    if raw != b"SDK Example,demo,SIM001,1.0.0\\n":
        raise ValueError("Unexpected identity")
    return {"manufacturer": "SDK Example", "model": "demo", "serial": "SIM001",
            "firmware": "1.0.0", "source": "device"}


def parse_voltage(raw):
    if not isinstance(raw, bytes) or len(raw) > 128 or not raw.endswith(b"\\n"):
        raise ValueError("Incomplete frame")
    value = float(raw.decode("ascii"))
    if not math.isfinite(value):
        raise ValueError("Nonfinite reading")
    return value
'''

TEST = """import asyncio
import json
from importlib.resources import files
from benchweave_sdk.testing import MockContext, MockHost
from benchweave_sdk.validation import validate_descriptor, validate_result
from __PLUGIN__.adapter import create_plugin
from __PLUGIN__.protocol import transaction


def test_identify_and_read():
    async def run():
        descriptor = json.loads(files("__PLUGIN__").joinpath("descriptor.json").read_text())
        validate_descriptor(descriptor)
        host = MockHost([(transaction("identify"), {"data": b"SDK Example,demo,SIM001,1.0.0\\n"}),
                         (transaction("read"), {"data": b"3.3\\n"})])
        plugin = create_plugin()
        context = MockContext("op-1", deadline_monotonic=1.0)
        await plugin.open(descriptor, host, context)
        for verb, args in (("identify", {}), ("read", {"parameter": "voltage"})):
            request = {"operation_id": "op-1", "verb": verb, "arguments": args}
            result = await plugin.execute(request, context)
            validate_result(result, request)
            assert result["status"] == "ok"
        host.assert_complete()
        await plugin.close(context)
        await plugin.close(context)
    asyncio.run(run())


def test_quiet_lifecycle():
    from benchweave_sdk.conformance import check_lifecycle
    descriptor = json.loads(files("__PLUGIN__").joinpath("descriptor.json").read_text())
    asyncio.run(check_lifecycle(create_plugin, descriptor))


def test_no_transmit_before_dispatch():
    async def run():
        for reason in ("cancelled", "expired", "bad_arguments", "wrong_context"):
            host = MockHost([])
            plugin = create_plugin()
            context = MockContext("op", deadline_monotonic=1.0)
            await plugin.open({}, host, context)
            request = {"operation_id": "op", "verb": "read",
                       "arguments": {"parameter": "voltage"}}
            if reason == "cancelled":
                context.cancel()
            elif reason == "expired":
                host.advance(1.0)
            elif reason == "bad_arguments":
                request["arguments"]["parameter"] = "unknown"
            else:
                context.operation_id = "other"
            result = await plugin.execute(request, context)
            validate_result(result, request)
            assert result["status"] == "error"
            assert result["error"]["dispatch_state"] == "not_dispatched"
            assert not context.dispatched and not host.transfers
            await plugin.close(MockContext("cleanup", deadline_monotonic=2.0))
    asyncio.run(run())


def test_uncertain_response_after_dispatch():
    async def run():
        responses = ({"data": b"nan\\n"}, {"data": b"3.3"}, {"data": b"\\xff\\n"},
                     ConnectionError("lost"), TimeoutError("expired"), RuntimeError("host"))
        for response in responses:
            host = MockHost([(transaction("read"), response)])
            plugin = create_plugin()
            context = MockContext("op", deadline_monotonic=1.0)
            await plugin.open({}, host, context)
            request = {"operation_id": "op", "verb": "read",
                       "arguments": {"parameter": "voltage"}}
            result = await plugin.execute(request, context)
            validate_result(result, request)
            assert result["status"] == "unknown"
            assert result["error"]["dispatch_state"] == "unknown"
            assert context.dispatched
            host.assert_complete()
            await plugin.close(context)
    asyncio.run(run())
"""


AI_GUIDE = """# Build a BenchWeave device plugin with AI

Use one prompt at a time and review its result. This project is a synthetic
read-only example. The hardware is the device; this Python package is its plugin.
Use plugins/<manufacturer>/<name>/ as the project root in a plugin collection,
with src/<package>/ inside. That project can become its own external repository.
The SDK implementation lives separately in BenchWeave's packages/sdk/.

## Project layout

Run installation, pytest and uv build from the directory containing pyproject.toml.
The generated project contains README.md, this AI-GUIDE.md, CLAUDE.md (agent
notes for the repository root), tests/test_plugin.py, and src/<package>/ with
__init__.py, adapter.py, protocol.py, descriptor.json, protocol.md, vectors.json
and skills/ — the seeded agent skills (develop-plugin for the authoring
workflow, drive-device as the synthetic demo driver to rewrite). The protocol
and vectors files begin as synthetic evidence; the skills are distributable
content inside the package.

With --with-ui, the SDK also generates UI-GUIDE.md at the project root and
presentation.json, binding-catalogue.json and ui/manifest.json inside src/<package>/.
Add optional settings schemas under src/<package>/ui/settings/, complete presets
under src/<package>/ui/presets/, and declared assets under src/<package>/ui/assets/.
Those optional directories and configuration files are author-supplied. See
UI-GUIDE.md when present. For configuration without UI, use src/<package>/config/
with settings.schema.json and presets/. When UI presents those settings, keep one
authoritative copy under ui/settings/ and ui/presets/ rather than duplicating it.

Optional project-root docs/compatibility.md and docs/qualification.md describe
supported models/firmware and supervised hardware evidence. firmware/README.md
and firmware/release-notes/ can hold vendor source/checksum references and upgrade
constraints. They do not enable SDK firmware discovery or flashing. Additional
tests/test_configuration.py, tests/test_presentation.py and tests/fixtures/ can
cover those features and firmware-specific protocol exchanges. These files are
recommended author additions, not generated by the scaffold.

Keep distributable resources inside src/<package>/ for inclusion in the wheel.
Generate uv.lock for development dependencies; build outputs go in dist/.
Keep credentials, deployment configuration and collected runtime data outside the
plugin source package. A preset is configuration, not a retained measurement.

## 1. Establish the facts

> Inspect this project and my supplied device manual/protocol evidence. List
> exact model/firmware support, intended operations, command sources, ranges,
> transport bounds, side effects and unknowns. Map them to OTDP 0.2.0 and adapter
> API 1.1. Do not invent commands. Propose a small implementation plan before
> editing. Do not contact hardware, flash firmware, energise outputs or publish.

## 2. Implement against mocks

> Implement the agreed protocol in protocol.py and async adapter.py. Update the
> descriptor and trace every command to evidence. Keep create_plugin no-argument,
> construction/open free of device I/O, and transport behind supplied scoped
> services. Mark dispatch before transmit, honour monotonic deadlines and
> cancellation, never retry silently, and preserve uncertain outcomes. Keep
> imports relative within this package or standard-library-only for the current
> gateway loader. Run the synthetic identify/read example before replacing it.

## 3. Demonstrate behaviour

> Extend the exact-exchange tests for supported operations, wrong correlation,
> invalid arguments, expiry/cancellation before and after dispatch, malformed or
> truncated responses, transport loss and repeated/failed-open cleanup. Use SDK
> validation and conformance helpers. Run the tests and show commands/results.
> List applicable S/C/M requirements these helpers do not prove. Label synthetic
> evidence separately from device captures. Do not claim hardware qualification.

## 4. Review and qualify separately

> Prepare this exact revision, descriptor, compatibility claims and evidence for
> an independent review using BenchWeave's AI device integration reviewer role.
> Report defects and missing evidence with closure tests. Draft a supervised
> hardware qualification plan; do not execute it without separate authority.

## 5. Prepare a release for owner review

> Build the plugin wheel and source distribution. Prepare the registry manifest,
> exact payload inventory/hashes, dependency locks, licence, provenance and
> evidence status required by the registry contract; the seeded skills under
> src/<package>/skills/ are catalogued with the skill role, and CLAUDE.md ships
> only if the publisher chooses to include it (as documentation). A Python wheel
> is not a registry admission bundle. Test the installed plugin against the
> supported gateway version. Show me the artefacts and remaining gaps before
> publishing.

The SDK does not install a plugin into a live gateway. A Docker deployment needs
an admitted bundle and gateway deployment configuration; an SDK development
install changes only the development environment. Capture/profile operations,
physical providers and complete OTDP conformance require additional work beyond
this starter. Async test timeouts cannot stop blocking or hostile Python code;
use an isolated process without bench access for candidate-code execution.
"""


CLAUDE_MD = """# Agent notes for this plugin project

Project: synthetic BenchWeave device plugin (package `__PLUGIN__`). This
file is developer tooling at the repository root: it never enters the wheel
(`packages = ["src/__PLUGIN__"]`), and if a release ever ships it, the
registry manifest catalogues it as `documentation`, not `skill`.

## Commands

- Run the tests: `pytest`
- Validate the descriptor offline: `benchweave-sdk check src/__PLUGIN__/descriptor.json`
- Build the wheel and sdist: `uv build`
- Pin dependencies: `uv lock`

## Where things are

- `AI-GUIDE.md` — the five build-out prompts (facts, implementation,
  demonstration, review, release)
- `src/__PLUGIN__/skills/` — the seeded agent skills:
  `develop-plugin/SKILL.md` (authoring workflow, elicitation questions,
  release mechanics) and `drive-device/SKILL.md` (the synthetic demo
  driver; rewrite it for the real device)
- `src/__PLUGIN__/descriptor.json` — the OTDP descriptor under check

## Safety rails

This project is synthetic: do not contact hardware, flash firmware or
energise outputs while authoring plugin code, and publish nothing without
separate authority from the project owner.
"""

DEVELOP_SKILL = """---
name: __PLUGIN__-plugin-development
description: Author, implement, check and release the __PLUGIN__ BenchWeave
  device plugin - elicitation questions keyed to the real descriptor
  surfaces, adapter discipline, standalone-MCP shape and release mechanics.
---

# Developing the __PLUGIN__ plugin

Work prompt-first: establish facts before editing, implement against mocks,
then review and release. The descriptor is the contract; every command you
wire must trace to evidence. Do not invent commands or capabilities.

## 1. Elicitation - ask before generating

Ask all of these before writing the descriptor, adapter or manifest. Each
question names the real surface it fills.

**Device identity** (`identity`): manufacturer and exact model? Which
`strategy` - `scpi_idn`, `uart_identity`, `commissioned` or `adapter`?
`firmware_policy` `listed` (then which `supported_firmware` versions?) or
`commissioning_required`?

**Transport** (`transport`, nine types): `serial`, `uart_scpi`,
`uart_json`, `lan_scpi`, `usbtmc`, `can`, `i2c`, `spi` or `custom`? Which
`connection_key`? Which settings - serial/uart: `baud`, `data_bits`,
`parity`, `stop_bits`, `rtscts`, `max_frame_bytes` (uart_json also
`framing`; uart_scpi also `max_response_bytes`, `read_termination`,
`write_termination`); lan_scpi: `port`, `protocol`, `read_termination`,
`write_termination`, `max_response_bytes`; usbtmc: `vid`, `pid`,
`read_termination`, `write_termination`, `max_response_bytes`; can:
`receive_id`, `fd`, `extended`, `payload_length`; i2c: `address`; spi:
`mode`, `speed_hz`, `bits_per_word`; custom: `protocol_reference`?

**Class and profiles** (`profiles`, `actions`): which of the twelve OTDP
classes - `otdp.dc_psu/1.0.0`, `otdp.dmm/1.0.0`, `otdp.oscilloscope/1.0.0`,
`otdp.logic_analyser/1.0.0`, `otdp.function_generator/1.0.0`,
`otdp.electronic_load/1.0.0`, `otdp.smu/1.0.0`, `otdp.daq/1.0.0`,
`otdp.embedded_controller/1.0.0`, `otdp.switch_matrix/1.0.0`,
`otdp.spectrum_analyser/1.0.0`, `otdp.vna/1.0.0`? Which profile ids to
declare, and which class action contracts to adopt?

**Operations** (`capabilities` must equal `operations` keys - S01): which
of the ten verbs - `identify`, `read`, `write`, `invoke`, `capture`,
`reset`, `self_test`, `get_errors`, `stream_subscribe`,
`stream_unsubscribe`? Per verb the operation policy: `timeout_ms`,
`side_effect` (`none` or `state_change`), `retry` (`never` or
`idempotent`), `cancellable`, `completion` (`dispatched`, `acknowledged`,
`readback` or `physical`)?

**Parameters** (`parameters`): per parameter the `name`, `type`
(`float`, `int`, `bool`, `enum`, `string`), `access` (`ro`, `wo`, `rw`),
`semantic` (`measurement`, `setpoint`, `state`, `configuration`), `unit`,
`description`? A `range` or `enum_values`? `string_constraints`?
`hazard_class` (`unknown`, `none`, `low`, `high`)? `read_policy`
(`max_age_ms`, `destructive`) and `write_policy` (completion, effect,
retry, tolerances, settling)? `binding` kind? Names unique (S01), bounds
not reversed (S02)?

**Channels, capture and streams** (the capture/decode case): `channels`
entries - `id`, `label`, `role`, `quantities`, `parameter_names`? Which
`capture_formats` and `capture_limits`? Which `stream_limits`?

**Diagnostics** (`diagnostics`): self-test and error-reporting surface?
Which of `self_test` / `get_errors` apply?

**Adapter** (`integration.adapter`): `entry_point`, `api_version`,
`version`, `dependencies`, `permissions` (for example
`scoped_transport`)?

**Evidence and provenance** (`provenance`): command sources
(`sources[]` title/reference/revision)? `test_vectors` paths? Evidence
level per report - `structural`, `simulated` or `hardware`?

**Release**: package `kind` - `profile`, `descriptor` or
`implementation`? (See section 5.)

**Safety boundary**: what must never be done without separate authority?
While authoring: do not contact hardware, flash firmware or energise
outputs, and publish nothing without separate authority.

## 2. Firmware development

Keep vendor source and checksum references under `firmware/` and release
notes under `firmware/release-notes/`; they document constraints only.
Decide `listed` (exact supported versions) versus `commissioning_required`
(no implied tested firmware) from real evidence. The SDK does no firmware
discovery and no flashing - ever.

## 3. Adapter creation

Implement `protocol.py` and async `adapter.py` against the real adapter
surface: `open(descriptor, services, context)`, `execute(request,
context)`, `next_event`, `close`. Keep `create_plugin` no-argument and
construction/open free of device I/O. Mark dispatch before transmit,
honour monotonic deadlines and cancellation, never retry silently,
preserve uncertain outcomes, and keep imports relative within this
package or standard-library-only for the gateway loader. The SDK's
`MockHost`/`MockContext` exchanges (see tests/test_plugin.py) are the
reference pattern for exact-exchange tests.

## 4. Standalone MCP server (workflow, not shipped machinery)

The SDK ships no MCP server. To use this plugin standalone, write a
project-local MCP server: construct the adapter via `create_plugin()`,
implement the five-method host contract over a real transport (settings
from the descriptor) - `transfer(transaction, context)`, `monotonic()`,
`utc_now()`, `close_transport(context)`, `record_evidence(entry,
context)` - and expose the descriptor's verbs as MCP tools, keeping the
dispatch-before-transmit, deadline and uncertain-outcome disciplines.
Keep it out of the distributed package unless the owner decides
otherwise.

## 5. Release

Build the wheel and sdist, then prepare the registry manifest with the
exact payload inventory and hashes (`benchweave-sdk inventory` emits the
path/bytes/sha256 rows; the manifest assigns roles). File roles for this
project's files: the skills under `src/__PLUGIN__/skills/` are `skill`;
`descriptor.json` is `descriptor`; `protocol.md` and `vectors.json` are
`test` evidence inputs per the registry specification's role list
(`profile`, `descriptor`, `implementation`, `schema`, `test`,
`documentation`, `licence`, `sbom`, `build_provenance`,
`dependency_lock`, `skill`); the root `CLAUDE.md` is `documentation` if
the publisher ships it at all - it is dev tooling by default. An
`implementation`-kind payload must contain `implementation`, `sbom`,
`build_provenance` and `dependency_lock` entries. Evidence reports carry
their honest level - `structural`, `simulated` or `hardware`; synthetic
results are never hardware qualification. Publication happens only with
the owner's review: publish nothing without separate authority.
"""

DRIVE_SKILL = """---
name: __PLUGIN__-device-operation
description: Drive the __PLUGIN__ synthetic demo device - identify and read
  the voltage parameter over the mock exchanges; the template to rewrite
  for the real instrument.
---

# Driving the __PLUGIN__ device (synthetic demo)

This skill drives the SEEDED SYNTHETIC PROTOCOL, not a real instrument:
`ID?` + LF returns `SDK Example,demo,SIM001,1.0.0` + LF; `V?` + LF returns
a finite ASCII voltage + LF. Supported verbs are `identify` and `read` of
the `voltage` parameter (unit V, read-only measurement).

Open the adapter via `create_plugin()`, `open(descriptor, services,
context)`, then execute `identify` (no arguments) and `read`
(`{"parameter": "voltage"}`). Expect `status: "ok"` with identity fields
or a measurement value; the mock exchanges in `vectors.json` and
`tests/test_plugin.py` are the exact reference.

**Rewrite this skill for the real device.** It is the honesty placeholder
the synthetic `adapter.py` and `protocol.py` already are: replace the
exchanges, verbs, parameters, error handling and any capture/decode flow
with the real instrument's evidenced behaviour, and keep every command
traceable to the manual or captures.

Safety: authoring and driving stay on mocks - do not contact hardware,
flash firmware or energise outputs from plugin code, and publish nothing
without separate authority.
"""


def descriptor_for(package: str) -> dict[str, Any]:
    """Build the synthetic plugin descriptor for ``package``.

    The descriptor advertises the synthetic identify/read protocol
    (OTDP descriptor 0.2.0, adapter API 1.1) with
    ``<package>.adapter:create_plugin`` as its entry point.

    Parameters
    ----------
    package
        Lowercase Python package name of the generated project.

    Returns
    -------
    dict
        A descriptor that passes ``validate_descriptor``.
    """
    policy = {
        "timeout_ms": 1000,
        "side_effect": "none",
        "retry": "never",
        "cancellable": True,
        "completion": "acknowledged",
    }
    return {
        "otdp_version": "0.2.0",
        "descriptor_version": "0.1.0",
        "id": f"dev.example.{package.replace('_', '-')}",
        "display_name": "SDK synthetic example",
        "description": "Simulated read-only protocol; not hardware qualified.",
        "identity": {
            "strategy": "adapter",
            "manufacturer": "SDK Example",
            "model": "demo",
            "firmware_policy": "listed",
            "supported_firmware": ["1.0.0"],
        },
        "integration": {
            "mode": "adapter",
            "adapter": {
                "entry_point": f"{package}.adapter:create_plugin",
                "api_version": "1.1",
                "version": "0.1.0",
                "dependencies": [],
                "permissions": ["scoped_transport"],
            },
        },
        "transport": {
            "type": "serial",
            "connection_key": "example_device",
            "settings": {
                "baud": 115200,
                "data_bits": 8,
                "parity": "none",
                "stop_bits": 1,
                "rtscts": False,
                "max_frame_bytes": 128,
            },
        },
        "capabilities": ["identify", "read"],
        "operations": {"identify": policy, "read": policy},
        "parameters": [
            {
                "name": "voltage",
                "description": "Synthetic voltage",
                "type": "float",
                "access": "ro",
                "semantic": "measurement",
                "unit": "V",
                "binding": {"kind": "adapter", "key": "voltage"},
                "read_policy": {"max_age_ms": 0, "destructive": False},
            }
        ],
        "required_features": ["otdp.core/0.1.0", "otdp.adapter/0.1.0"],
        "provenance": {
            "sources": [
                {"title": "SDK synthetic protocol", "reference": "protocol.md", "revision": "0.1.0"}
            ],
            "test_vectors": [
                {
                    "id": "example",
                    "path": "vectors.json",
                    "purpose": "Synthetic identify/read exchanges",
                }
            ],
        },
    }


def create_project(destination: Path, package: str) -> None:
    """Write a complete synthetic plugin project under ``destination``.

    Generates ``pyproject.toml``, a README, ``AI-GUIDE.md``, a working
    read-only adapter with its synthetic protocol, a validated
    ``descriptor.json``, synthetic protocol evidence, and a pytest suite
    that exercises the adapter against SDK mocks. Nothing generated
    contacts hardware or claims qualification.

    Parameters
    ----------
    destination
        Project directory to create; it must not already exist.
    package
        Lowercase package name (``[a-z][a-z0-9_]*``) that does not
        shadow the SDK or a stdlib module.

    Raises
    ------
    ValueError
        If the package name is invalid or reserved.
    FileExistsError
        If the destination directory already exists.

    Examples
    --------
    >>> from pathlib import Path
    >>> from benchweave_sdk.scaffold import create_project
    >>> create_project(Path("plugins/acme/cooler"), "acme_cooler")
    """
    if (
        not re.fullmatch(r"[a-z][a-z0-9_]*", package)
        or keyword.iskeyword(package)
        or package in RESERVED_PACKAGE_NAMES
    ):
        raise ValueError(
            "Use a lowercase Python package name that does not shadow the SDK or the stdlib"
        )
    descriptor = descriptor_for(package)
    validate_descriptor(descriptor)
    destination.mkdir(parents=True, exist_ok=False)
    pyproject = f'''[build-system]
requires = ["hatchling>=1.26"]
build-backend = "hatchling.build"
[project]
name = "{package.replace("_", "-")}"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = []
[project.optional-dependencies]
test = ["benchweave-sdk=={__version__}", "pytest>=8.0"]
[tool.hatch.build.targets.wheel]
packages = ["src/{package}"]
'''
    root = f"src/{package}"
    contents = {
        "pyproject.toml": pyproject,
        "README.md": (
            "# Device plugin starter\n\nSynthetic only. Create a virtual environment, "
            "install the matching SDK wheel and `uv pip install -e '.[test]'`. "
            "Run `pytest`, then `uv build`. Pin dependencies with `uv lock`. "
            "See AI-GUIDE.md. Choose a licence before distribution.\n"
        ),
        "AI-GUIDE.md": AI_GUIDE,
        f"{root}/__init__.py": '"""Synthetic device plugin."""\n',
        f"{root}/adapter.py": ADAPTER,
        f"{root}/protocol.py": PROTOCOL,
        f"{root}/descriptor.json": json.dumps(descriptor, indent=2) + "\n",
        f"{root}/protocol.md": (
            "# Synthetic protocol\n\nID? + LF returns SDK Example,demo,SIM001,1.0.0 + LF. "
            "V? + LF returns finite ASCII volts + LF. No real device is claimed.\n"
        ),
        f"{root}/vectors.json": json.dumps(
            {
                "evidence": "synthetic",
                "exchanges": [
                    {"request": "ID?\n", "response": "SDK Example,demo,SIM001,1.0.0\n"},
                    {"request": "V?\n", "response": "3.3\n"},
                ],
            },
            indent=2,
        )
        + "\n",
        "tests/test_plugin.py": TEST.replace("__PLUGIN__", package),
        "CLAUDE.md": CLAUDE_MD.replace("__PLUGIN__", package),
        f"{root}/skills/develop-plugin/SKILL.md": DEVELOP_SKILL.replace("__PLUGIN__", package),
        f"{root}/skills/drive-device/SKILL.md": DRIVE_SKILL.replace("__PLUGIN__", package),
    }
    for relative, content in contents.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
