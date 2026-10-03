"""The adapter session: loading, lifecycle, and per-operation contexts.

The loader imports the plugin's adapter module with no side effects beyond
the import itself (the project's ``src/`` goes on ``sys.path``; the
descriptor's ``integration.adapter.entry_point`` names the factory), then
validates the descriptor — and the presentation documents, when the project
declares them — before anything binds a port (SW-05). :class:`PluginSession`
then drives one adapter instance through the strict ``Adapter`` lifecycle:
``open`` binds descriptor and services, ``execute`` runs one operation per
fresh context, ``close`` is idempotent-tolerant (REG-1).

Every operation context is bounded by the descriptor's OWN operation policy
(``operations[verb].timeout_ms``): the plugin's declared bound is the bound;
the host adds no uncommissioned envelope (A02's posture). Lifecycle contexts
(open/close — not descriptor verbs) use the strictest declared timeout, a
derived-not-invented bound.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchweave_sdk.interfaces import Adapter, HostServices
from benchweave_sdk.presentation import read_file
from benchweave_sdk.validation import validate_descriptor


class PluginLoadError(ValueError):
    """A plugin project could not be loaded or validated; always prefixed."""


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    """A validated plugin project ready to serve.

    ``adapter_factory`` is ``None`` on a DEGRADED load (§4.5): the project's
    documents validated, but its adapter entry point failed to import or
    resolve — ``load_diagnostic`` carries the prefixed reason, device
    operations answer ``not_ready``, and the pages still render.
    """

    project_root: Path
    package: str
    descriptor: dict[str, Any]
    descriptor_sha256: str
    plugin_version: str
    adapter_factory: Any | None = None
    has_presentation: bool = False
    load_diagnostic: str | None = None

    @property
    def device_id(self) -> str:
        """The one device this session serves, named by the descriptor."""
        transport = self.descriptor.get("transport", {})
        return str(transport.get("connection_key") or self.package)

    @property
    def readable_parameters(self) -> list[dict[str, Any]]:
        """Descriptor parameters a readings page may show (ro or rw)."""
        rows = []
        for parameter in self.descriptor.get("parameters", []):
            if parameter.get("access") in ("ro", "rw"):
                rows.append(parameter)
        return rows

    @property
    def package_dir(self) -> Path:
        """The plugin package directory (``src/<package>/``)."""
        return self.project_root / "src" / self.package


def mock_exchanges(
    plugin: LoadedPlugin,
) -> list[tuple[dict[str, Any], dict[str, Any] | Exception]]:
    """Build the I1 scripted exchanges from the plugin's own evidence.

    The starter protocol's evidence file (``vectors.json``) carries the
    exact request/response byte pairs, and the descriptor's transport
    settings carry the frame bound — the script is derived from the plugin's
    declared data, not hardcoded host knowledge of any one plugin. The
    transaction shape is the scaffold protocol's own (``stream_exchange``,
    LF termination); a plugin whose adapter speaks a different shape will
    fail the mock's exact-match discipline honestly (R7's accepted bound).
    """
    vectors = json.loads(read_file(plugin.package_dir / "vectors.json"))
    settings = plugin.descriptor.get("transport", {}).get("settings", {})
    max_bytes = int(settings.get("max_frame_bytes", 0)) or 128
    script: list[tuple[dict[str, Any], dict[str, Any] | Exception]] = []
    for row in vectors.get("exchanges", []):
        transaction = {
            "kind": "stream_exchange",
            "data": str(row["request"]).encode("ascii"),
            "max_bytes": max_bytes,
            "termination": "lf",
            "exact_bytes": None,
        }
        script.append((transaction, {"data": str(row["response"]).encode("ascii")}))
    if not script:
        raise PluginLoadError(
            f"standalone_transport_script: no exchanges in {plugin.package_dir / 'vectors.json'}"
        )
    return script


def load_plugin_project(project_root: Path) -> LoadedPlugin:
    """Load and validate one plugin project; refuse before any port binds.

    Raises
    ------
    PluginLoadError
        With a ``standalone_plugin_*:`` prefix (SW-05) carrying the SDK's
        own diagnostic text for validation failures.
    """
    root = project_root.expanduser().resolve()
    src = root / "src"
    if not src.is_dir():
        raise PluginLoadError(f"standalone_plugin_project: no src/ under {root}")
    candidates = sorted(p.parent for p in src.glob("*/descriptor.json"))
    if len(candidates) != 1:
        raise PluginLoadError(
            f"standalone_plugin_project: expected exactly one src/*/descriptor.json "
            f"under {root}, found {len(candidates)}"
        )
    package_dir = candidates[0]
    package = package_dir.name
    descriptor_path = package_dir / "descriptor.json"
    try:
        raw = read_file(descriptor_path)
    except (OSError, ValueError) as exc:
        raise PluginLoadError(f"standalone_plugin_invalid: {descriptor_path}: {exc}") from exc
    try:
        descriptor = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PluginLoadError(f"standalone_plugin_invalid: {descriptor_path}: {exc}") from exc
    try:
        validate_descriptor(descriptor)
    except (ValueError, KeyError, TypeError) as exc:
        raise PluginLoadError(f"standalone_plugin_invalid: {exc}") from exc

    entry_point = str(
        descriptor.get("integration", {}).get("adapter", {}).get("entry_point", "")
    )
    module_name, _, factory_name = entry_point.partition(":")
    adapter: Any | None = None
    diagnostic: str | None = None
    if not module_name.startswith(f"{package}.") or not factory_name:
        # Adapter-failure class (§4.5): the entry point STRING is part of
        # the adapter surface, not the documents — a malformed one degrades
        # (layout renders, device ops not_ready) instead of refusing.
        diagnostic = (
            f"standalone_plugin_entry_point: {entry_point} does not name a factory "
            f"inside the {package} package"
        )
    else:
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        try:
            module = importlib.import_module(module_name)
            adapter = getattr(module, factory_name)
        except (ImportError, AttributeError) as exc:
            diagnostic = f"standalone_plugin_import: {entry_point}: {exc}"

    presentation_path = package_dir / "presentation.json"
    has_presentation = presentation_path.is_file()
    if has_presentation:
        from benchweave_sdk.presentation import load_validated_preview_inputs

        try:
            load_validated_preview_inputs(
                presentation_path,
                descriptor_path,
                package_dir,
                package_dir / "binding-catalogue.json",
                firmware=None,
                features=frozenset(),
                panels=frozenset(),
            )
        except (ValueError, OSError) as exc:
            raise PluginLoadError(f"standalone_plugin_invalid: {exc}") from exc

    plugin_version = str(
        descriptor.get("integration", {}).get("adapter", {}).get("version", "unknown")
    )
    return LoadedPlugin(
        project_root=root,
        package=package,
        descriptor=descriptor,
        descriptor_sha256=hashlib.sha256(raw).hexdigest(),
        plugin_version=plugin_version,
        adapter_factory=adapter,
        has_presentation=has_presentation,
        load_diagnostic=diagnostic,
    )


class HostOperationContext:
    """A live ``OperationContext``: real clock, descriptor-declared deadline.

    ``deadline_monotonic`` is ``time.monotonic() + timeout_ms / 1000`` where
    ``timeout_ms`` comes from the descriptor's own operation policy for the
    verb being executed (SW-13): the host mints no envelope of its own.
    """

    def __init__(self, operation_id: str, *, timeout_ms: int) -> None:
        if not operation_id or not math.isfinite(float(timeout_ms)) or timeout_ms <= 0:
            raise ValueError("A context needs an identity and a positive finite timeout")
        self.operation_id = operation_id
        self.dataset_id: str | None = None
        self.deadline_monotonic = time.monotonic() + timeout_ms / 1000
        self.dispatched = False
        self._cancelled = False

    def is_cancelled(self) -> bool:
        """Report whether :meth:`cancel` has been called."""
        return self._cancelled

    def cancel(self) -> None:
        """Cancel cooperatively; subsequent transfers must fail, not transmit."""
        self._cancelled = True

    async def mark_dispatch_started(self) -> None:
        """Record the dispatch marker immediately before the first transmit."""
        self.dispatched = True


class PluginSession:
    """One adapter session over a per-connection transport (SW-04's shape).

    The services object is minted FRESH by ``services_factory`` on every
    connect: a disconnect closes that transport for good (the mock's
    ``close_transport`` never reopens), and a reconnect must start a new
    scripted conversation from its establishment head — reusing one
    process-lifetime host leaves a fresh adapter talking to a dead
    transport mid-cycle (the M1 fold). Connecting then establishes the
    device's identity once (the gateway's own admission shape: identity is
    an establishment fact, not a pollable); ``device_get`` serves the
    established identity afterwards. Over the deterministic scripted
    transport the cached identity is exact; a real transport (I3)
    re-establishes on connect the same way.
    """

    def __init__(
        self, plugin: LoadedPlugin, services_factory: Callable[[], HostServices]
    ) -> None:
        self._plugin = plugin
        self._services_factory = services_factory
        self._adapter: Adapter | None = None
        self.identity: dict[str, Any] | None = None
        self.connected = False

    @property
    def plugin(self) -> LoadedPlugin:
        return self._plugin

    @property
    def device_id(self) -> str:
        return self._plugin.device_id

    def _lifecycle_timeout_ms(self) -> int:
        """The strictest declared operation timeout (open/close are not verbs)."""
        policies = self._plugin.descriptor.get("operations", {})
        timeouts = [int(row.get("timeout_ms", 0)) for row in policies.values()]
        return max(timeouts) if timeouts else 1000

    def _context(self, operation_id: str, timeout_ms: int) -> HostOperationContext:
        return HostOperationContext(operation_id, timeout_ms=timeout_ms)

    def verb_timeout_ms(self, verb: str) -> int:
        """The descriptor's declared timeout for ``verb`` (A02: its bound)."""
        policy = self._plugin.descriptor.get("operations", {}).get(verb, {})
        timeout_ms = int(policy.get("timeout_ms", 0))
        if timeout_ms <= 0:
            raise KeyError(f"standalone_verb_unbounded: {verb}")
        return timeout_ms

    async def connect(self) -> None:
        """Open the adapter session and establish the device's identity.

        ``open`` is contractually device-I/O free; the establishment
        ``identify`` that follows is the session's first exchange. A failed
        establishment fails the connect (the adapter closes again) — an
        adapter that cannot say who it is has not connected.
        """
        if self.connected or self._adapter is not None:
            raise RuntimeError("standalone_session_connected")
        if self._plugin.adapter_factory is None:
            # The degraded load (§4.5): documents validated, the adapter
            # did not — the diagnostic IS the refusal's reason.
            raise RuntimeError(
                self._plugin.load_diagnostic or "standalone_plugin_not_ready"
            )
        adapter = self._plugin.adapter_factory()
        context = self._context(
            f"open-{uuid.uuid4().hex[:8]}", self._lifecycle_timeout_ms()
        )
        await adapter.open(self._plugin.descriptor, self._services_factory(), context)
        self._adapter = adapter
        self.connected = True
        try:
            if "identify" in self._plugin.descriptor.get("capabilities", []):
                envelope = await self.execute("identify", {})
                if envelope.get("status") != "ok":
                    raise RuntimeError(
                        "standalone_connect_failed: "
                        f"{(envelope.get('error') or {}).get('code', 'unknown')}"
                    )
                data = envelope.get("data")
                if isinstance(data, dict):
                    self.identity = dict(data)
        except BaseException:
            await self.close()
            raise

    async def execute(self, verb: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one operation envelope through the open adapter."""
        if self._adapter is None or not self.connected:
            raise RuntimeError("standalone_session_not_open")
        timeout_ms = self.verb_timeout_ms(verb)
        operation_id = f"op-{uuid.uuid4().hex[:8]}"
        context = self._context(operation_id, timeout_ms)
        request = {"operation_id": operation_id, "verb": verb, "arguments": arguments}
        return await self._adapter.execute(request, context)

    async def close(self) -> None:
        """Close the session; tolerates repeated calls (Adapter.close rule)."""
        adapter, self._adapter = self._adapter, None
        self.connected = False
        if adapter is not None:
            context = self._context(
                f"close-{uuid.uuid4().hex[:8]}", self._lifecycle_timeout_ms()
            )
            await adapter.close(context)
