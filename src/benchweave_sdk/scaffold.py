"""Generate a standalone, read-only synthetic plugin; never contact hardware."""

from __future__ import annotations

import json
import keyword
import re
import shutil
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
The generated project contains README.md, this AI-GUIDE.md, tests/test_plugin.py,
and src/<package>/ with __init__.py, adapter.py, protocol.py, descriptor.json,
protocol.md and vectors.json. The latter two begin as synthetic evidence.

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
> transport bounds, side effects and unknowns. Map them to OTDP 0.1.1 and adapter
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
> evidence status required by the registry contract. A Python wheel is not a
> registry admission bundle. Test the installed plugin against the supported
> gateway version. Show me the artefacts and remaining gaps before publishing.

The SDK does not install a plugin into a live gateway. A Docker deployment needs
an admitted bundle and gateway deployment configuration; an SDK development
install changes only the development environment. Capture/profile operations,
physical providers and complete OTDP conformance require additional work beyond
this starter. Async test timeouts cannot stop blocking or hostile Python code;
use an isolated process without bench access for candidate-code execution.
"""


def descriptor_for(package: str) -> dict[str, Any]:
    """Build the synthetic plugin descriptor for ``package``.

    The descriptor advertises the synthetic identify/read protocol
    (OTDP descriptor 0.1.1, adapter API 1.1) with
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
        "otdp_version": "0.1.1",
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
        If the destination directory — or a leftover ``.partial`` staging
        sibling — already exists; a dangling symlink occupying either name
        counts as existing.

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
    # is_symlink() catches a dangling symlink occupying the name, which
    # exists() reports as absent but which would break the final rename.
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage into a sibling directory and rename at the end, so an interrupted
    # run never leaves a half-generated project at the destination. A
    # pre-existing staging path is refused, never deleted: it is either not
    # ours (the tool must not destroy content it did not create) or the
    # leftover of a hard-killed run, which the operator removes deliberately.
    staging = destination.with_name(destination.name + ".partial")
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(f"Staging path already exists: {staging}; remove it and retry")
    staging.mkdir()
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
    }
    try:
        for relative, content in contents.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
