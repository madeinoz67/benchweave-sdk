"""The operations seam: the only mutation path, shared by REST, HTML and MCP.

A13's one-contract rule applied to standalone: every surface is an adapter
over :meth:`StandaloneSeam.call`; no route, tool or template touches the
adapter directly. The seam owns the closed refusal model —

- an operation name outside the catalogue is ``invalid_request`` (the client
  asked for something the contract does not contain);
- a declared but unimplemented operation is ``unavailable`` with a
  ``reason: increment_deferral`` detail (never silently absent);
- arguments are validated against the catalogue's input schema
  (``invalid_request`` with the validator's findings);
- adapter-reported failures surface with their envelope preserved verbatim in
  ``details`` (``status``, ``error.code``, ``dispatch_state``) so permission,
  transport and device rejection stay distinct outcomes end to end (SW-12,
  REG-2's ambiguity-preservation as the pass-through rule);
- exceptions escaping the adapter map honestly: a ``ConformanceError`` is the
  scripted transport refusing an exchange (exhausted or mismatched —
  ``unavailable``); ``TimeoutError``/``ConnectionError`` are ``not_ready``
  (NFR-O2: transport loss and expiry are not-ready outcomes); anything else
  is ``internal_error``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import getpass
import hashlib
import json
import struct
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from benchweave_sdk.capture import capture_root as resolve_capture_root
from benchweave_sdk.presentation import read_file, validate_preset
from benchweave_sdk.testing import ConformanceError

from . import catalogue
from .errors import SeamError
from .events import EventBus
from .library import CaptureLibrary
from .session import (
    HostOperationContext,
    PluginLoadError,
    PluginSession,
    evict_plugin_modules,
    load_plugin_project,
    project_py_digest,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # The presentation model and the observation ring import the
    # ``benchweave-ui-html`` extra at MODULE level; the seam keeps them OUT
    # of its own module-level chain (PR #97's Windows red: cli.py imports
    # this module at line 28, and a default install's console entry died
    # at plots.py's ui_html import before the extras guard could answer).
    # The CLI module chain imports nothing from the extra set (the A-E
    # contract); the lazy imports below run only when a seam is
    # constructed — inside the guarded serve/mcp bodies.
    from .plots import ObservationRing
    from .presentation import HostPresentation

    class _CaptureCapable(Protocol):
        """The capture members the lifecycle drives on a capture-capable
        services object (the runtime check is the callable-capability gate
        in ``_op_capture_start``; this type is the static mirror)."""

        def configure_capture(
            self, capture_id: str, *, metadata: dict[str, Any], max_bytes: int | None
        ) -> None: ...

        def capture_progress(self, capture_id: str) -> int: ...

        async def artifact_finalise(
            self, capture_id: str, metadata: dict[str, Any], context: Any
        ) -> dict[str, Any]: ...

        async def artifact_abort(self, capture_id: str) -> None: ...

#: The adapter envelope error codes → interface codes (SW-12 distinctness kept:
#: the adapter's own code and dispatch_state ride in ``details`` verbatim).
_ADAPTER_CODE_MAP: dict[str, str] = {
    "INVALID_ARGUMENT": "invalid_request",
    "UNSUPPORTED": "invalid_request",
    # The device said no against its own state — a state-based refusal is
    # a conflict on this interface, distinct from not_ready (the device
    # cannot be reached) and from invalid_request (the ask was malformed);
    # the adapter's own envelope still rides the details verbatim.
    "DEVICE_REJECTED": "conflict",
    "TIMEOUT": "not_ready",
    "TRANSPORT_ERROR": "not_ready",
    "PROTOCOL_ERROR": "unavailable",
    "INTERNAL_ERROR": "internal_error",
}

#: The operations whose success is a state change (I2c §4.2): exactly these
#: publish an event. Reads (``host_info``, discovery, ``device_get``,
#: ``parameter_read``, ``events_get`` itself) mutate nothing and publish
#: nothing — a watcher must not generate traffic by watching.
_STATE_EVENT_OPS: frozenset[str] = frozenset(
    {
        "device_connect",
        "device_disconnect",
        "parameter_stage",
        "parameter_apply",
        "preset_apply",
    }
)

#: The dispatch surface of the CURRENT call (SW-34: the originating surface
#: is host knowledge, supplied by the dispatch layer — web/rest/mcp — never
#: by clients; ``capture_start`` records it into the SW-54 metadata). The
#: contextvar is task-local, so concurrent calls each carry their own.
_SURFACE: ContextVar[str | None] = ContextVar("bws_dispatch_surface", default=None)

#: Bytes per sample by capture format (ruling 2: the count bound is
#: samples × bytes-per-sample).
_BYTES_PER_SAMPLE: dict[str, int] = {"waveform_f64le": 8, "raw_binary": 1}

#: The capture watchdog's poll quantum (s): the loop wakes on adapter-task
#: completion, a stop request, or this timeout — whichever comes first.
_CAPTURE_POLL_S = 0.05

#: The capture_progress coalescing window (SW-26/NFR-Q3): at most one
#: progress row per this many seconds, carrying the staged-byte total.
_PROGRESS_WINDOW_S = 0.25

#: How long the watchdog waits at a reached bound for a cooperative adapter
#: to return on its own before cancelling the operation context (the
#: backstop, not the primary mechanism).
_BOUND_GRACE_S = 0.30

#: ``capture_stop``'s settle budget beyond the verb's own declared timeout
#: (grace included): an adapter that ignores even context cancellation
#: cannot hold the stop call forever.
_STOP_SETTLE_MARGIN_S = 5.0

#: Raw (``max_points: 0``) series serving is refused above this sample
#: count — the catalogue's own authored maximum (10M), not a second number.
_RAW_SAMPLE_CEILING = 10_000_000

#: The primary-artifact extensions by manifest format (the manifest's
#: ``format`` field stays the source of truth; the filename is derived).
_PRIMARY_SUFFIXES = {"waveform_f64le": ".f64", "raw_binary": ".bin"}


def sdk_version() -> str:
    """The SDK version this host runs on, derived — never a literal."""
    try:
        return metadata.version("benchweave-sdk")
    except metadata.PackageNotFoundError:  # pragma: no cover - dev-checkout edge
        return "unknown"


class StandaloneSeam:
    """One seam over one adapter session; the surfaces are its adapters."""

    def __init__(
        self,
        session: PluginSession,
        *,
        transport_kind: str,
        unattended: bool = False,
        reload_wrapper: Callable[[Any], Any] | None = None,
        serial_ports: Any = None,
        serial_device_path: str | None = None,
        capture_root: Any | None = None,
    ) -> None:
        self._session = session
        self._transport_kind = transport_kind
        self._serial_ports = serial_ports
        self._serial_device_path = serial_device_path
        self._capture_root = capture_root
        self._capture: Any | None = None
        self._capture_outcomes: dict[str, dict[str, Any]] = {}
        # The capture library (I3b slice 2) is LAZY: constructed on the
        # first library op or capture terminal, never at seam construction —
        # a seam that never touches captures must not create or lock a
        # root (and the lockfile is one-library-per-root by design).
        self._capture_library: CaptureLibrary | None = None
        # Lazy by contract (see the module's TYPE_CHECKING note): these run
        # inside the guarded serve/mcp bodies, never at the console entry's
        # module import.
        from .plots import ObservationRing
        from .presentation import HostPresentation

        # The presentation model is host state owned by the seam (the PRD
        # §6 diagram's named component): built once, read by every surface.
        self._presentation = HostPresentation(
            package_dir=session.plugin.package_dir,
            has_presentation=session.plugin.has_presentation,
        )
        # The bounded observation ring (§3.3): fed by every successful
        # parameter read — host-observed samples, nothing fabricated.
        self.observation_ring: ObservationRing = ObservationRing()
        # The staging map (I2b §4.1): HOST state, never device state (the
        # per-connection services precedent). Insertion order is the
        # staging order ``parameter_apply`` honors; staging performs no I/O
        # and a refused apply retains every staged value.
        self._staged: dict[str, Any] = {}
        # The preset digests, pinned once at construction (CON-1's posture
        # at host scale): listing and apply verify the bytes on disk
        # against this pin, so a preset tampered while the host runs
        # refuses. A file added after construction is not served — the
        # running host serves the configuration it started with.
        self._preset_digests: dict[str, str] = self._pin_presets()
        # The seam event bus (I2c §4.2): one append-only order for REST,
        # the browser stream and MCP. The seam is the only mutation path,
        # so it is the only publisher.
        self.events = EventBus()
        # Authoring/reload state (I2c §4.2): unattended mode waives the Q11
        # confirmation; the adapter-code digest is computed at load and
        # recomputed at reload (the mechanical adapter/contract
        # discrimination); the pending confirmation is a STATE, never an
        # error; _capture_in_flight is the reload guard's capture leg —
        # no capture exists until I3 arms it.
        self._unattended = unattended
        self._reload_wrapper = reload_wrapper
        self._adapter_sha256 = project_py_digest(session.plugin)
        self._pending_reload: dict[str, Any] | None = None
        self._capture_in_flight = False
        self._discovery_cache: list[dict[str, Any]] | None = None
        self.reload_state: dict[str, Any] | None = None
        # The op-vs-reload mutex (the refute lanes' serialization class):
        # a device-mutating sequence (an apply's write→read-back span, a
        # staging write against the map an apply is flushing) must not
        # interleave with a reload's quiet-close→swap or with each other —
        # every await point inside those spans is an interleaving window.
        # The lock is loop-level (single event loop); it serializes async
        # interleavings, which is exactly the class the lanes reproduced.
        self._op_mutex = asyncio.Lock()

    @property
    def session(self) -> PluginSession:
        return self._session

    @property
    def transport_kind(self) -> str:
        return self._transport_kind

    @property
    def presentation(self) -> HostPresentation:
        """The host presentation model (built once, seam-owned)."""
        return self._presentation

    @property
    def staged(self) -> dict[str, Any]:
        """The staging map (host state): parameter name → staged value."""
        return self._staged

    @property
    def unattended(self) -> bool:
        """Whether the host runs in unattended mode (Q11's waiver)."""
        return self._unattended

    @property
    def pending_reload(self) -> dict[str, Any] | None:
        """The pending Q11 confirmation, when one is waiting."""
        return self._pending_reload

    @property
    def discovery_cache(self) -> list[dict[str, Any]] | None:
        """The last discovery result (host state): None until a scan runs.
        GET / serves this on the serial transport — never a live scan
        (NFR-O3: a page load must not transmit to candidate ports)."""
        return self._discovery_cache

    def _correlation(self, supplied: str | None) -> str:
        return supplied or f"bws-{uuid.uuid4().hex[:12]}"

    def _refuse_degraded(self, correlation: str) -> None:
        """Device operations answer ``not_ready`` on a degraded load (§4.5):
        the documents validated, the adapter did not — the load diagnostic
        rides the refusal so the author sees WHY on every surface."""
        diagnostic = self._session.plugin.load_diagnostic
        if diagnostic is not None:
            raise self._fail(
                "not_ready", diagnostic, correlation, load_diagnostic=diagnostic
            )

    def _fail(
        self, code: str, message: str, correlation_id: str, **details: Any
    ) -> SeamError:
        return SeamError(code, message, correlation_id=correlation_id, details=details)

    async def call(
        self,
        operation: str,
        arguments: dict[str, Any] | None = None,
        *,
        correlation_id: str | None = None,
        surface: str | None = None,
    ) -> dict[str, Any]:
        """Execute one catalogue operation; return its data or raise ``SeamError``.

        ``surface`` is the dispatch layer's own identity (SW-34: host
        knowledge — the web/rest/mcp adapters pass it; clients cannot).
        """
        correlation = self._correlation(correlation_id)
        token = _SURFACE.set(surface)
        try:
            try:
                row = catalogue.spec(operation)
                if row is None:
                    raise self._fail(
                        "invalid_request",
                        f"unknown operation: {operation}",
                        correlation,
                        closed_catalogue=(
                            catalogue.deferred_operations() + catalogue.served_operations()
                        ),
                    )
                if not row.implemented:
                    raise self._fail(
                        "unavailable",
                        f"operation not implemented in this increment: {operation}",
                        correlation,
                        reason="increment_deferral",
                    )
                self._validate(row.name, arguments or {}, correlation)
                handler = getattr(self, f"_op_{row.name}")
                result = await handler(arguments or {}, correlation)
            except SeamError as exc:
                # EVERY seam-exit refusal rides the bus (FOLD-E): the unknown
                # operation, the deferred operation, the argument-validation
                # refusal and the handler's own — a watching page must see
                # what was refused and why, not only handler failures.
                self.events.publish(
                    "refused",
                    {"operation": operation, "code": exc.code, "message": exc.message},
                )
                raise
            if row.name in _STATE_EVENT_OPS:
                self.events.publish(row.name, self._event_data(row.name, result))
            return cast(dict[str, Any], result)
        finally:
            _SURFACE.reset(token)

    def _event_data(self, operation: str, result: dict[str, Any]) -> dict[str, Any]:
        """The event payload for one state change: small, derived from the
        operation's own result — never a second source of truth."""
        data: dict[str, Any] = {"device_id": result.get("device_id")}
        if operation == "parameter_stage":
            data["parameter"] = result.get("parameter")
            data["staged"] = list(result.get("staged", []))
        elif operation == "parameter_apply":
            data["applied_count"] = len(result.get("applied", []))
        elif operation == "preset_apply":
            data["preset_id"] = result.get("preset_id")
            data["applied_count"] = len(result.get("applied", []))
        return data

    def _validate(self, name: str, arguments: dict[str, Any], correlation: str) -> None:
        from jsonschema import Draft202012Validator

        row = catalogue.spec(name)
        assert row is not None and row.implemented
        validator = Draft202012Validator(row.input_schema)
        findings = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))
        if findings:
            raise self._fail(
                "invalid_request",
                "arguments failed schema validation",
                correlation,
                findings=[
                    {"path": list(error.absolute_path), "message": error.message}
                    for error in findings
                ],
            )

    # --- handlers ----------------------------------------------------------

    async def _op_host_info(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        from .presentation import SUPPORTED_FEATURES, SUPPORTED_PANELS

        plugin = self._session.plugin
        return {
            "mode": "standalone",
            "absent_guarantees": list(catalogue.ABSENT_GUARANTEES),
            "served_operations": list(catalogue.served_operations()),
            "deferred_operations": list(catalogue.deferred_operations()),
            "plugin": {
                "package": plugin.package,
                "version": plugin.plugin_version,
                "descriptor_sha256": plugin.descriptor_sha256,
            },
            "transport": self._transport_kind,
            "sdk_version": sdk_version(),
            "presentation": {
                "features": sorted(SUPPORTED_FEATURES),
                "panels": sorted(SUPPORTED_PANELS),
                "unavailable_pages": list(self._presentation.unavailable_pages),
            },
        }

    async def _op_device_discover(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if self._transport_kind == "serial":
            from .serial import discover_serial_devices

            session = self._session
            try:
                devices = await discover_serial_devices(
                    session.plugin,
                    hooks=self._serial_ports,
                    connected_device=(
                        self._serial_device_path if session.connected else None
                    ),
                    connected_identity=session.identity,
                )
            except (RuntimeError, ValueError, OSError) as exc:
                # The scan's real failure classes (a missing pyserial, an
                # enumerate error, an invalid declared hint) raise BEFORE
                # any SeamError exists — surface them typed, never as a
                # raw 500 through the interfaces, and cache nothing.
                raise self._fail(
                    "not_ready", f"device scan refused: {exc}", correlation
                ) from exc
            self._discovery_cache = devices
            return {"devices": devices}
        descriptor = self._session.plugin.descriptor
        identity = descriptor.get("identity", {})
        transport = descriptor.get("transport", {})
        return {
            "devices": [
                {
                    "id": self._session.device_id,
                    "manufacturer": str(identity.get("manufacturer", "")),
                    "model": str(identity.get("model", "")),
                    "transport": str(transport.get("type", "")),
                    "connection_key": str(transport.get("connection_key", "")),
                }
            ]
        }

    async def _op_device_connect(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        self._refuse_degraded(correlation)
        if self._session.connected:
            raise self._fail(
                "conflict",
                f"device already connected: {arguments['device_id']}",
                correlation,
            )
        try:
            await self._session.connect()
        except ConformanceError as exc:
            raise self._fail(
                "unavailable", f"transport refused the exchange: {exc}", correlation
            ) from exc
        except (TimeoutError, ConnectionError) as exc:
            raise self._fail(
                "not_ready", f"device not ready: {exc}", correlation
            ) from exc
        except RuntimeError as exc:
            raise self._fail("not_ready", str(exc), correlation) from exc
        return {"device_id": self._session.device_id, "connected": True}

    async def _op_device_disconnect(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        await self._session.close()
        return {"device_id": self._session.device_id, "connected": False}

    async def _op_device_get(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        self._refuse_degraded(correlation)
        if not self._session.connected:
            raise self._fail(
                "not_ready", "device is not connected", correlation
            )
        if self._session.identity is None:
            raise self._fail(
                "not_ready", "device identity not established", correlation
            )
        return dict(self._session.identity)

    async def _op_parameter_read(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if arguments["device_id"] != self._session.device_id:
            raise self._fail(
                "not_found", f"no such device: {arguments['device_id']}", correlation
            )
        self._refuse_degraded(correlation)
        if not self._session.connected:
            raise self._fail("not_ready", "device is not connected", correlation)
        name = arguments["parameter"]
        known = {
            row.get("name"): row
            for row in self._session.plugin.readable_parameters
        }
        if name not in known:
            raise self._fail(
                "not_found",
                f"no such readable parameter: {name}",
                correlation,
            )
        data = await self._execute("read", {"parameter": name}, correlation)
        self.observation_ring.record(
            name, time.monotonic() * 1000.0, data.get("value")
        )
        return data

    # --- staged/apply and presets (I2b §4.1) ---------------------------------

    def _parameters(self) -> dict[str, dict[str, Any]]:
        return {
            str(row.get("name")): row
            for row in self._session.plugin.descriptor.get("parameters", [])
            if isinstance(row.get("name"), str)
        }

    def _stageable(self, name: str, value: Any, correlation: str) -> dict[str, Any]:
        """Validate one staged value against the descriptor's OWN declaration
        (A02: access, declared type, declared range) — refuse ``invalid_request``
        naming the parameter. Only ``rw`` parameters stage: a write-only
        parameter could never produce the read-back SW-23 requires."""
        row = self._parameters().get(name)
        if row is None:
            raise self._fail(
                "invalid_request", f"no such writable parameter: {name}", correlation
            )
        access = str(row.get("access", ""))
        if access != "rw":
            raise self._fail(
                "invalid_request",
                f"parameter is not writable: {name} (access={access})",
                correlation,
            )
        declared = str(row.get("type", ""))
        valid_type = (
            (declared == "float" and isinstance(value, (int, float))
             and not isinstance(value, bool))
            or (declared == "int" and isinstance(value, int)
                and not isinstance(value, bool))
            or (declared == "bool" and isinstance(value, bool))
            or (declared == "string" and isinstance(value, str))
            or (declared == "enum" and isinstance(value, str)
                and value in [str(v) for v in row.get("enum_values", [])])
        )
        if not valid_type:
            raise self._fail(
                "invalid_request",
                f"staged value does not match declared type {declared}: {name}",
                correlation,
            )
        bounds = row.get("range")
        if (
            declared in ("float", "int")
            and isinstance(bounds, list)
            and len(bounds) == 2
        ):
            low, high = float(bounds[0]), float(bounds[1])
            try:
                numeric = float(value)
            except (OverflowError, ValueError) as exc:
                # A JSON integer can exceed the numeric format; the closed
                # refusal model answers typed, never a bare 500.
                raise self._fail(
                    "invalid_request",
                    f"staged value is not representable: {name}",
                    correlation,
                ) from exc
            if not low <= numeric <= high:
                raise self._fail(
                    "invalid_request",
                    f"staged value outside declared range [{low:g}, {high:g}]: {name}",
                    correlation,
                )
        return row

    async def _op_parameter_stage(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        # Under the op mutex: a stage must not land between an in-flight
        # apply's last write and its staging-map clear — the apply flushes
        # exactly the batch it fixed, and a value staged mid-flight is the
        # NEXT apply's business, not something the clear may eat.
        async with self._op_mutex:
            if arguments["device_id"] != self._session.device_id:
                raise self._fail(
                    "not_found", f"no such device: {arguments['device_id']}", correlation
                )
            self._refuse_degraded(correlation)
            name = arguments["parameter"]
            value = arguments["value"]
            self._stageable(name, value, correlation)
            self._staged[name] = value
            return {
                "device_id": self._session.device_id,
                "parameter": name,
                "value": value,
                "staged": list(self._staged),
            }

    async def _apply_batch(
        self, batch: dict[str, Any], correlation: str
    ) -> list[dict[str, Any]]:
        """Write exactly ``batch`` (in its own order) under the descriptor's
        declared operation policies, then re-read each written parameter:
        the rows this returns come ONLY from the read-back (SW-23). The
        batch is SCOPED — the caller's staging map is neither read nor
        written here: ``parameter_apply`` flushes its own map on success,
        ``preset_apply`` applies exactly the preset's settings and leaves
        prior staging untouched (FOLD-A: an abandoned staged write never
        lands under a preset action). Both verbs are guarded BEFORE any
        frame (FOLD-B: a missing read policy refuses like a missing write
        policy — never a landed write followed by a laundered error). Any
        failure stops the apply and retains the caller's staging map — a
        device rejection is never a silent discard."""
        self._refuse_degraded(correlation)
        if not self._session.connected:
            raise self._fail("not_ready", "device is not connected", correlation)
        for verb in ("write", "read"):
            try:
                self._session.verb_timeout_ms(verb)
            except KeyError as exc:
                raise self._fail(
                    "unavailable",
                    f"{exc}: the descriptor declares no {verb} operation policy",
                    correlation,
                ) from exc
        names = list(batch)
        for name in names:
            await self._execute(
                "write",
                {"parameter": name, "value": batch[name]},
                correlation,
            )
        rows: list[dict[str, Any]] = []
        for name in names:
            data = await self._execute("read", {"parameter": name}, correlation)
            self.observation_ring.record(
                name, time.monotonic() * 1000.0, data.get("value")
            )
            rows.append(
                {
                    "parameter": name,
                    "value": data.get("value"),
                    "unit": data.get("unit"),
                    "observed_at": str(data.get("observed_at", "")),
                    "age_ms": int(data.get("age_ms", 0)),
                    "quality": str(data.get("quality", "")),
                    "source": str(data.get("source", "")),
                }
            )
        return rows

    async def _op_parameter_apply(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        # Under the op mutex for the WHOLE span (empty-check, batch,
        # clear): the write→read-back sequence and the staging-map flush
        # are one operation — a reload or stage interleaving inside it is
        # a cross-adapter chimera or a vanished stage respectively.
        async with self._op_mutex:
            if arguments["device_id"] != self._session.device_id:
                raise self._fail(
                    "not_found", f"no such device: {arguments['device_id']}", correlation
                )
            if not self._staged:
                raise self._fail(
                    "invalid_request", "nothing is staged to apply", correlation
                )
            applied = await self._apply_batch(self._staged, correlation)
            self._staged.clear()
            return {"device_id": self._session.device_id, "applied": applied}

    def _pin_presets(self) -> dict[str, str]:
        """Digest every declared preset once, at construction."""
        digests: dict[str, str] = {}
        presets_dir = self._session.plugin.package_dir / "config" / "presets"
        if presets_dir.is_dir():
            for path in sorted(presets_dir.glob("*.json")):
                digests[path.stem] = hashlib.sha256(read_file(path)).hexdigest()
        return digests

    def repin_preset(self, preset_id: str) -> str:
        """Re-pin one preset's serving digest after the host's OWN authorized
        write (the authoring ``preset_put``). The construction pin governs
        bytes the host did not write; this moves the pin WITH the host's
        write so the running host serves its authorized configuration
        without a reload, and returns the new digest."""
        path = (
            self._session.plugin.package_dir
            / "config"
            / "presets"
            / f"{preset_id}.json"
        )
        digest = hashlib.sha256(read_file(path)).hexdigest()
        self._preset_digests[preset_id] = digest
        return digest

    def _preset_rows(self, correlation: str) -> list[dict[str, Any]]:
        """The plugin's declared presets under ``config/presets/`` — the
        scaffold's documented configuration home — each row carrying the
        CONSTRUCTION-pinned digest, verified against the bytes on disk
        before listing (CON-1's posture at host scale). Local files only;
        no device I/O."""
        rows: list[dict[str, Any]] = []
        for preset_id, digest in self._preset_digests.items():
            path = (
                self._session.plugin.package_dir
                / "config"
                / "presets"
                / f"{preset_id}.json"
            )
            try:
                raw = read_file(path)
            except (OSError, ValueError) as exc:
                raise self._fail(
                    "invalid_request",
                    f"unreadable preset document: {preset_id}: {exc}",
                    correlation,
                ) from exc
            if hashlib.sha256(raw).hexdigest() != digest:
                raise self._fail(
                    "invalid_request",
                    f"preset bytes drifted since startup: {preset_id}",
                    correlation,
                    preset_id=preset_id,
                    finding="digest_mismatch",
                )
            try:
                document = json.loads(raw)
            except ValueError as exc:
                raise self._fail(
                    "invalid_request",
                    f"malformed preset document: {preset_id}: {exc}",
                    correlation,
                ) from exc
            if not isinstance(document, dict):
                raise self._fail(
                    "invalid_request",
                    f"preset document is not an object: {preset_id}",
                    correlation,
                )
            rows.append(
                {
                    "id": preset_id,
                    "title": str(document.get("title", preset_id)),
                    "sha256": digest,
                }
            )
        return rows

    def _preset_bytes(self, preset_id: str, correlation: str) -> bytes:
        digest = self._preset_digests.get(preset_id)
        if digest is None:
            raise self._fail(
                "not_found", f"no such preset: {preset_id}", correlation
            )
        path = (
            self._session.plugin.package_dir
            / "config"
            / "presets"
            / f"{preset_id}.json"
        )
        try:
            raw = read_file(path)
        except (OSError, ValueError) as exc:
            raise self._fail(
                "invalid_request",
                f"unreadable preset document: {preset_id}: {exc}",
                correlation,
            ) from exc
        if hashlib.sha256(raw).hexdigest() != digest:
            raise self._fail(
                "invalid_request",
                f"preset bytes drifted since startup: {preset_id}",
                correlation,
                preset_id=preset_id,
                finding="digest_mismatch",
            )
        return raw

    async def _op_preset_list(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        return {"presets": self._preset_rows(correlation)}

    async def _op_preset_apply(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        # Under the op mutex for the WHOLE span (firmware gate,
        # validation, the transient batch's write→read-back): the
        # batch never enters _staged, so without the mutex a reload
        # landing inside the span serves the write on the old adapter
        # and the read-back on the new one — a cross-adapter chimera
        # reported SUCCESS (SW-23's read-back rule broken).
        async with self._op_mutex:
            if arguments["device_id"] != self._session.device_id:
                raise self._fail(
                    "not_found", f"no such device: {arguments['device_id']}", correlation
                )
            self._refuse_degraded(correlation)
            if not self._session.connected:
                raise self._fail("not_ready", "device is not connected", correlation)
            identity = self._session.identity
            if identity is None:
                raise self._fail(
                    "not_ready",
                    "device identity not established: the firmware gate cannot run",
                    correlation,
                )
            firmware = str(identity.get("firmware", ""))
            if not firmware:
                raise self._fail(
                    "not_ready",
                    "device identity carries no firmware: the firmware gate cannot run",
                    correlation,
                )
            preset_id = arguments["preset_id"]
            raw = self._preset_bytes(preset_id, correlation)
            try:
                preset = json.loads(raw)
            except ValueError as exc:
                raise self._fail(
                    "invalid_request",
                    f"malformed preset document: {preset_id}: {exc}",
                    correlation,
                ) from exc
            plugin = self._session.plugin
            try:
                descriptor_raw = read_file(plugin.package_dir / "descriptor.json")
                settings_raw = read_file(
                    plugin.package_dir / "config" / "settings.schema.json"
                )
            except (OSError, ValueError) as exc:
                raise self._fail(
                    "invalid_request",
                    f"unreadable configuration documents: {exc}",
                    correlation,
                ) from exc
            if hashlib.sha256(descriptor_raw).hexdigest() != plugin.descriptor_sha256:
                raise self._fail(
                    "invalid_request",
                    "descriptor bytes drifted since load",
                    correlation,
                    finding="digest_mismatch",
                )
            report = validate_preset(
                raw,
                descriptor_raw=descriptor_raw,
                settings_schema_raw=settings_raw,
                firmware=firmware,
            )
            if not report.valid:
                findings = [
                    {"code": finding.code, "path": finding.path, "message": finding.message}
                    for finding in report.findings
                ]
                if any(finding.code == "incompatible_firmware" for finding in report.findings):
                    supported = [
                        str(row) for row in (preset or {}).get("supported_firmware", [])
                    ]
                    raise self._fail(
                        "conflict",
                        f"preset firmware mismatch: device {firmware}, "
                        f"preset {preset_id} supports {supported}",
                        correlation,
                        device_firmware=firmware,
                        preset_firmware=supported,
                    )
                raise self._fail(
                    "invalid_request",
                    f"preset failed validation: {preset_id}",
                    correlation,
                    findings=findings,
                )
            settings = (preset or {}).get("settings")
            if not isinstance(settings, dict):
                raise self._fail(
                    "invalid_request",
                    f"preset settings are not an object: {preset_id}",
                    correlation,
                )
            for name, value in settings.items():
                self._stageable(str(name), value, correlation)
            # Scoped: apply exactly the preset's settings through a transient
            # batch — previously staged values are neither applied nor
            # discarded (FOLD-A; I2c's reload guard treats the same condition
            # as a guard, and so does this path).
            batch = {str(name): value for name, value in settings.items()}
            applied = await self._apply_batch(batch, correlation)
            return {
                "device_id": self._session.device_id,
                "preset_id": preset_id,
                "applied": applied,
            }
    # --- reload (I2c §4.2, SW-38 + Q11) --------------------------------------

    def _reload_guards(self, correlation: str) -> None:
        """The conflict guards every reload path runs: a staged value that
        was never applied, and a capture in flight (no capture exists until
        I3; the flag is the state I3's capture_start will hold)."""
        if self._staged:
            raise self._fail(
                "conflict",
                "a staged value is unapplied: apply or clear staging before "
                "reloading",
                correlation,
            )
        if self._capture_in_flight:
            raise self._fail(
                "conflict",
                "a capture is in flight: stop it before reloading",
                correlation,
            )

    async def reload_plugin(self, source: str, *, confirmed: bool = False) -> dict[str, Any]:
        """Reload the loaded project: guards, re-import, re-validate; on a
        load failure the PREVIOUS version stays loaded and the diagnostics
        return. The Q11 branch: when the reload would change ADAPTER CODE
        (the package's ``.py`` digest differs) and a session is connected
        and the host is attended, the reload does not run — it PENDS, the
        advisory rides the bus, and the operator confirms in the UI. In
        unattended mode the same change proceeds (the PRD's benches with
        no energy-sourcing instruments case).

        Under the op mutex for the whole path: a reload must not begin
        inside a device-mutating span (the serialization class).
        """
        async with self._op_mutex:
            try:
                return await self._reload_body(source, confirmed=confirmed)
            except SeamError as exc:
                # The reload family raises OUTSIDE seam.call, so its
                # refusals publish 'refused' themselves (FOLD-E) — a
                # watching page must see Q11's own conflict.
                self.events.publish(
                    "refused",
                    {
                        "operation": "plugin_reload",
                        "code": exc.code,
                        "message": exc.message,
                    },
                )
                raise

    async def confirm_reload(self, source: str) -> dict[str, Any]:
        """The operator's UI confirmation of a pending Q11 reload: re-run
        the full path (guards and validation included — the files may have
        changed again) with the confirmation granted."""
        async with self._op_mutex:
            try:
                if self._pending_reload is None:
                    raise self._fail(
                        "invalid_request", "no reload is waiting for confirmation", ""
                    )
                return await self._reload_body(source, confirmed=True)
            except SeamError as exc:
                self.events.publish(
                    "refused",
                    {
                        "operation": "plugin_reload_confirm",
                        "code": exc.code,
                        "message": exc.message,
                    },
                )
                raise

    async def _reload_body(
        self, source: str, *, confirmed: bool
    ) -> dict[str, Any]:
        from datetime import UTC, datetime

        correlation = self._correlation(None)
        self._reload_guards(correlation)
        project_root = self._session.plugin.project_root
        package = self._session.plugin.package
        # Re-import the CURRENT bytes: the import cache is evicted first so
        # the reload cannot hand back the previous adapter object.
        evict_plugin_modules(package, src_root=project_root / "src")
        try:
            loaded = load_plugin_project(project_root)
        except PluginLoadError as exc:
            raise self._fail(
                "invalid_request",
                f"reload refused, the previous version stays loaded: {exc}",
                correlation,
                diagnostic=str(exc),
            ) from exc
        next_adapter_sha256 = project_py_digest(loaded)
        if confirmed:
            pending = self._pending_reload or {}
            if loaded.adapter_factory is None:
                # The degraded-bind door (FOLD-B): the operator confirmed
                # specific working bytes; a load that cannot import its
                # adapter is not those bytes — refuse, keep the previous
                # WORKING version loaded (the confirm never binds the
                # host to broken code), and surface the diagnostic. The
                # pend stays: the operator can fix the files and confirm
                # the load that follows.
                raise self._fail(
                    "invalid_request",
                    "the confirmed reload would not load: "
                    f"{loaded.load_diagnostic}; the previous version stays "
                    "loaded and the confirmation stands",
                    correlation,
                    diagnostic=loaded.load_diagnostic,
                )
            shown = str(pending.get("adapter_sha256_next", ""))
            if shown and shown != next_adapter_sha256:
                # The confirmation binds to the digests it showed (FOLD-B):
                # the bytes changed after the pend, so the confirmation
                # covers code that no longer exists — re-pend with the
                # fresh digest instead of loading unconfirmed code.
                at = datetime.now(UTC).isoformat()
                message = (
                    "the adapter code changed again since the confirmation "
                    "was shown; a new confirmation is required"
                )
                self._pending_reload = {
                    "at": at,
                    "source": source,
                    "adapter_sha256_previous": self._adapter_sha256,
                    "adapter_sha256_next": next_adapter_sha256,
                }
                self.events.publish(
                    "reload_confirmation_required",
                    {"message": message, "source": source, "at": at},
                )
                return {
                    "status": "confirmation_required",
                    "message": message,
                    "adapter_changed": True,
                    "source": source,
                }
        adapter_changed = next_adapter_sha256 != self._adapter_sha256
        if (
            adapter_changed
            and self._session.connected
            and not self._unattended
            and not confirmed
        ):
            at = datetime.now(UTC).isoformat()
            message = (
                "the reload changes adapter code while a device is "
                "connected; confirm in the UI to proceed"
            )
            self._pending_reload = {
                "at": at,
                "source": source,
                "adapter_sha256_previous": self._adapter_sha256,
                "adapter_sha256_next": next_adapter_sha256,
            }
            self.events.publish(
                "reload_confirmation_required",
                {"message": message, "source": source, "at": at},
            )
            return {
                "status": "confirmation_required",
                "message": message,
                "adapter_changed": True,
                "source": source,
            }
        return await self._complete_reload(loaded, source)

    async def _complete_reload(
        self, loaded: Any, source: str
    ) -> dict[str, Any]:
        from datetime import UTC, datetime

        correlation = self._correlation(None)
        self._reload_guards(correlation)
        effective = self._reload_wrapper(loaded) if self._reload_wrapper else loaded
        was_connected = self._session.connected
        # Quiet/disconnect, then the atomic swap: everything after this
        # point serves the new plugin.
        await self._session.reload_plugin(effective)
        self._presentation = self._presentation.__class__(
            package_dir=self._session.plugin.package_dir,
            has_presentation=self._session.plugin.has_presentation,
        )
        self._preset_digests = self._pin_presets()
        # The observation ring belongs to the PREVIOUS plugin version:
        # samples from the old code would launder into the new version's
        # plots, so the ring resets with the plugin.
        self.observation_ring.clear()
        self._adapter_sha256 = project_py_digest(self._session.plugin)
        self._pending_reload = None
        reconnected = False
        refusal: dict[str, Any] | None = None
        if was_connected:
            try:
                await self._session.connect()
                reconnected = self._session.connected
            except (RuntimeError, TimeoutError, ConnectionError) as exc:
                refusal = {
                    "code": "not_ready",
                    "message": f"reload succeeded; reconnect refused: {exc}",
                }
        at = datetime.now(UTC).isoformat()
        plugin = self._session.plugin
        self.reload_state = {"at": at, "source": source}
        self.events.publish(
            "plugin_reloaded",
            {
                "package": plugin.package,
                "version": plugin.plugin_version,
                "descriptor_sha256": plugin.descriptor_sha256,
                "source": source,
                "at": at,
                "reconnected": reconnected,
            },
        )
        return {
            "status": "reloaded",
            "package": plugin.package,
            "version": plugin.plugin_version,
            "descriptor_sha256": plugin.descriptor_sha256,
            "reconnected": reconnected,
            "reconnect_refusal": refusal,
            "source": source,
        }

    # --- the event bus (I2c §4.2) -------------------------------------------

    async def _op_events_get(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        """Serve the bus after the caller's cursor. A read: publishes no
        event of its own, or watching would generate traffic."""
        cursor = int(arguments["after_id"])
        return {
            "events": self.events.after(cursor),
            "last_id": self.events.last_id(),
        }

    # --- the capture lifecycle (I3b slice 3) -------------------------------

    def _library(self, correlation: str) -> CaptureLibrary:
        """The seam's capture library, constructed lazily on first use. A
        second host process over the same root refuses here (the lockfile's
        two-writers hazard, surfaced as ``unavailable``)."""
        if self._capture_library is None:
            try:
                self._capture_library = CaptureLibrary(
                    resolve_capture_root(self._capture_root)
                )
            except ValueError as exc:
                raise SeamError(
                    "not_ready", f"capture root refused: {exc}", correlation_id=correlation
                ) from exc
            except RuntimeError as exc:
                raise SeamError(
                    "unavailable", str(exc), correlation_id=correlation
                ) from exc
        return self._capture_library

    def _capture_limits(self) -> dict[str, Any]:
        """The descriptor's declared ``capture_limits`` (the schema-mandated
        commissioning: declaring the capture capability requires them —
        A02's posture, the plugin's own bounds, never a host constant)."""
        limits = self._session.plugin.descriptor.get("capture_limits", {})
        return limits if isinstance(limits, dict) else {}

    def _resolve_capture_verb(self, correlation: str) -> str:
        """Ruling 6: the capture verb is descriptor-declared — ``capture``
        first, the declared ``invoke`` second, and no declaration at all is
        an explicit gap the refusal names."""
        operations = self._session.plugin.descriptor.get("operations", {})
        if "capture" in operations:
            return "capture"
        if "invoke" in operations:
            return "invoke"
        raise self._fail(
            "unavailable",
            "no capture verb is declared: neither 'capture' nor 'invoke' "
            "appears in the descriptor's operations policy",
            correlation,
        )

    def _capture_metadata(
        self,
        arguments: dict[str, Any],
        capture_id: str,
        bound: dict[str, Any],
        fmt: str,
    ) -> dict[str, Any]:
        """The SW-54 metadata sidecar, composed before dispatch: device and
        plugin identity, the dispatch surface (host knowledge), the local
        operator, the annotation fields, the effective start configuration
        read back from the validated arguments, the declared bound and
        format, and the terminal fields pinned at their start values."""
        plugin = self._session.plugin
        identity = self._session.identity or {}
        try:
            operator = getpass.getuser()
        except Exception:  # noqa: BLE001 - an environment with no user name
            operator = "unknown"
        return {
            "capture_id": capture_id,
            "device": {"id": plugin.device_id, "firmware": identity.get("firmware")},
            "plugin": {
                "package": plugin.package,
                "version": plugin.plugin_version,
                "descriptor_sha256": plugin.descriptor_sha256,
            },
            "surface": _SURFACE.get(),
            "operator": operator,
            "project": arguments.get("project"),
            "tags": list(arguments.get("tags", [])),
            "notes": str(arguments.get("notes", "")),
            "config": {
                key: value
                for key, value in arguments.items()
                if key not in {"device_id", "project", "tags", "notes"}
            },
            "declared": {"format": fmt, "bound": bound},
            "at": datetime.now(UTC).isoformat(),
            "pinned": False,
            "stop_reason": None,
        }

    async def _op_capture_start(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        if not self._session.connected:
            raise self._fail("not_ready", "device is not connected", correlation)
        if self._capture is not None:
            raise self._fail(
                "conflict",
                f"a capture is already in flight: {self._capture['capture_id']}",
                correlation,
            )
        if self._pending_reload is not None:
            raise self._fail(
                "conflict",
                "a plugin reload is waiting for confirmation; confirm or "
                "clear it before capturing",
                correlation,
            )
        services = self._session.services
        if not all(
            callable(getattr(services, name, None))
            for name in ("configure_capture", "capture_progress", "artifact_finalise")
        ):
            raise self._fail(
                "unavailable",
                "the connected transport's services do not implement capture "
                "(the mock transport's host does not; connect a "
                "capture-capable device)",
                correlation,
            )
        verb = self._resolve_capture_verb(correlation)
        capture_services = cast("_CaptureCapable", services)
        fmt = str(arguments.get("format", "raw_binary"))
        bytes_per_sample = _BYTES_PER_SAMPLE.get(fmt, 1)
        limits = self._capture_limits()
        if "count" in arguments:
            count = int(arguments["count"])
            max_samples = limits.get("max_samples")
            if max_samples is not None and count > int(max_samples):
                raise self._fail(
                    "invalid_request",
                    f"count {count} exceeds the descriptor's declared capture "
                    f"limit (max_samples {max_samples})",
                    correlation,
                )
            bound_kind = "count"
            bound_bytes = count * bytes_per_sample
            bound: dict[str, Any] = {"kind": "count", "count": count, "bytes": bound_bytes}
            deadline: float | None = None
        else:
            duration = float(arguments["duration_s"])
            bound_kind = "duration_s"
            bound_bytes = None
            bound = {"kind": "duration_s", "duration_s": duration}
            deadline = time.monotonic() + duration
        requested = arguments.get("max_bytes")
        ceiling = limits.get("max_bytes")
        reservation = requested
        if requested is not None and ceiling is not None:
            reservation = min(int(requested), int(ceiling))
        elif ceiling is not None:
            reservation = int(ceiling)
        if (
            bound_bytes is not None
            and reservation is not None
            and int(reservation) < bound_bytes
        ):
            raise self._fail(
                "invalid_request",
                f"the byte reservation ({reservation}) is below the count bound "
                f"({bound_bytes} bytes); raise max_bytes or lower the count",
                correlation,
            )
        capture_id = f"cap-{uuid.uuid4().hex[:12]}"
        metadata = self._capture_metadata(arguments, capture_id, bound, fmt)
        capture_services.configure_capture(
            capture_id, metadata=metadata, max_bytes=reservation
        )
        task, context = self._session.begin_verb(
            verb,
            {
                "capture_id": capture_id,
                **{
                    key: value
                    for key, value in arguments.items()
                    if key not in {"device_id", "project", "tags", "notes"}
                },
            },
        )
        state: dict[str, Any] = {
            "capture_id": capture_id,
            "verb": verb,
            "task": task,
            "context": context,
            "watcher": None,
            "stop_event": asyncio.Event(),
            "bound_kind": bound_kind,
            "bound_bytes": bound_bytes,
            "deadline": deadline,
            "started_at": metadata["at"],
            "format": fmt,
            "interval": arguments.get("sample_interval_s"),
            "unit": arguments.get("unit"),
            "metadata": metadata,
            "device_id": arguments["device_id"],
            "progress": 0,
        }
        self._capture = state
        state["watcher"] = asyncio.create_task(self._watch_capture(state))
        # The capture events ride the EXISTING bus (I2c's one-sequence
        # rule): started at arm time, progress coalesced by the watcher,
        # stopped at the terminal state — the /events stream and every
        # watcher surface see the same rows.
        self.events.publish(
            "capture_started",
            {
                "capture_id": capture_id,
                "device_id": arguments["device_id"],
                "bound": bound,
                "format": fmt,
            },
        )
        return {
            "capture_id": capture_id,
            "device_id": arguments["device_id"],
            "state": "capturing",
            "bound": bound,
            "format": fmt,
        }

    async def await_capture(self) -> dict[str, Any] | None:
        """Settle the in-flight capture's watcher and return its outcome row
        (``None`` when no capture is in flight). The deterministic drain the
        lifecycle tests and the shutdown close-down share."""
        state = self._capture
        if state is None:
            return None
        return await asyncio.shield(cast("asyncio.Task[dict[str, Any]]", state["watcher"]))

    async def _op_capture_stop(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        state = self._capture
        if state is None or state["capture_id"] != capture_id:
            raise self._fail(
                "not_found", f"no capture in flight: {capture_id}", correlation
            )
        state["stop_event"].set()
        timeout = (
            self._session.verb_timeout_ms(state["verb"]) / 1000
            + _BOUND_GRACE_S
            + _STOP_SETTLE_MARGIN_S
        )
        try:
            outcome = await asyncio.wait_for(
                asyncio.shield(
                    cast("asyncio.Task[dict[str, Any]]", state["watcher"])
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise self._fail(
                "internal_error",
                f"capture {capture_id} did not settle after the stop request",
                correlation,
            ) from exc
        manifest = self._published_manifest(capture_id)
        return {
            "capture_id": capture_id,
            "state": outcome["state"],
            "stop_reason": outcome["stop_reason"],
            "manifest": manifest,
        }

    def _published_manifest(self, capture_id: str) -> dict[str, Any] | None:
        """The published manifest read from disk, or ``None`` — the stop
        result's manifest is the artifact's own record, never a copy held
        in memory."""
        event = self._library("").root / capture_id
        path = event / "manifest.json"
        if not path.is_file():
            return None
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            return None

    def _row(
        self,
        capture_id: str,
        state_name: str,
        started_at: str,
        fmt: str,
        metadata: dict[str, Any],
        *,
        byte_length: int | None,
        sha256: str | None,
        stop_reason: str | None,
        progress_bytes: int | None,
    ) -> dict[str, Any]:
        """One capture_list row, exactly the catalogue's closed 13-key set."""
        return {
            "capture_id": capture_id,
            "state": state_name,
            "started_at": started_at,
            "format": fmt,
            "byte_length": byte_length,
            "sha256": sha256,
            "surface": metadata.get("surface"),
            "project": metadata.get("project"),
            "pinned": bool(metadata.get("pinned", False)),
            "tags": list(metadata.get("tags", [])),
            "notes": str(metadata.get("notes", "")),
            "stop_reason": stop_reason,
            "progress_bytes": progress_bytes,
        }

    def _capture_progress(self, state: dict[str, Any]) -> int:
        services = self._session.services
        progress = getattr(services, "capture_progress", None)
        if not callable(progress):
            return int(state.get("progress", 0))
        return int(progress(state["capture_id"]))

    async def _op_capture_list(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        library = self._library(correlation)
        rows: list[dict[str, Any]] = []
        for stored in library.list_captures():
            rows.append(
                self._row(
                    stored["capture_id"],
                    "published",
                    stored["started_at"],
                    stored["format"],
                    stored,
                    byte_length=stored["byte_length"],
                    sha256=stored["sha256"],
                    stop_reason=stored["stop_reason"],
                    progress_bytes=None,
                )
            )
        state = self._capture
        if state is not None:
            rows.append(
                self._row(
                    state["capture_id"],
                    "capturing",
                    state["started_at"],
                    state["format"],
                    state["metadata"],
                    byte_length=None,
                    sha256=None,
                    stop_reason=None,
                    progress_bytes=self._capture_progress(state),
                )
            )
        known = {row["capture_id"] for row in rows}
        for capture_id, outcome in self._capture_outcomes.items():
            # Aborted outcomes are SESSION state (ruling 5): listed here,
            # never served by capture_get — a later publish of the same id
            # (possible after an abort) replaces the outcome row.
            if capture_id not in known:
                rows.append(dict(outcome))
        rows.sort(
            key=lambda row: (row["started_at"], row["capture_id"]), reverse=True
        )
        return {"captures": rows}

    def _event_dir(self, capture_id: str, correlation: str) -> Path:
        """The event directory for a published capture id, refused for ids
        that are not one safe path segment (a hostile id must not name a
        directory outside the capture root)."""
        if not capture_id or Path(capture_id).name != capture_id or capture_id in {
            ".",
            "..",
        }:
            raise self._fail(
                "not_found", f"no published capture: {capture_id}", correlation
            )
        return self._library(correlation).root / capture_id

    async def _op_capture_get(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        event = self._event_dir(capture_id, correlation)
        manifest_path = event / "manifest.json"
        if not manifest_path.is_file():
            raise self._fail(
                "not_found", f"no published capture: {capture_id}", correlation
            )
        try:
            manifest = dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        except ValueError as exc:
            raise self._fail(
                "not_found",
                f"capture {capture_id} has an unparseable manifest",
                correlation,
            ) from exc
        metadata_path = event / "metadata.json"
        metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            except ValueError:
                loaded = None
            if isinstance(loaded, dict):
                metadata = loaded
        return {
            "capture_id": capture_id,
            "manifest": manifest,
            "metadata": metadata,
        }

    async def _op_capture_series(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        event = self._event_dir(capture_id, correlation)
        manifest_path = event / "manifest.json"
        if not manifest_path.is_file():
            raise self._fail(
                "not_found", f"no published capture: {capture_id}", correlation
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fmt = str(manifest.get("format", ""))
        if fmt != "waveform_f64le":
            raise self._fail(
                "invalid_request",
                f"capture_series serves waveform_f64le primaries; use "
                f"artifact_read for a {fmt or 'unknown'} capture",
                correlation,
            )
        count = int(manifest.get("sample_count", 0))
        interval = float(manifest.get("sample_interval_s", 0.0))
        suffix = _PRIMARY_SUFFIXES.get(fmt, ".data")
        payload = (event / f"{capture_id}{suffix}").read_bytes()[: count * 8]
        values = struct.unpack(f"<{len(payload) // 8}d", payload)
        points = [
            (index * interval, value) for index, value in enumerate(values)
        ]
        max_points = int(arguments.get("max_points", 2000))
        if max_points == 0:
            if len(points) > _RAW_SAMPLE_CEILING:
                raise self._fail(
                    "payload_too_large",
                    f"raw series serving is refused above "
                    f"{_RAW_SAMPLE_CEILING} samples ({len(points)}); request "
                    "a decimated series instead",
                    correlation,
                )
            served: list[tuple[float, float]] = points
            decimated = False
        else:
            # Lazy import: plots.py pulls the ui-html extra at module level
            # (the A-E contract keeps it out of the CLI import chain).
            from .plots import decimate_minmax

            served = decimate_minmax(points, columns=max_points)
            decimated = len(points) > max_points
        return {
            "capture_id": capture_id,
            "format": fmt,
            "decimated": decimated,
            "max_points": max_points,
            "points": [[x, y] for x, y in served],
        }

    async def _op_capture_annotate(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        library = self._library(correlation)
        if library.get(capture_id) is None:
            raise self._fail(
                "not_found", f"no published capture: {capture_id}", correlation
            )
        library.update_annotation(
            capture_id,
            notes=arguments.get("notes"),
            tags=arguments.get("tags"),
        )
        row = library.get(capture_id)
        assert row is not None
        return {
            "capture_id": capture_id,
            "notes": row["notes"],
            "tags": row["tags"],
        }

    async def _op_capture_pin(
        self, arguments: dict[str, Any], correlation: str, *, pinned: bool = True
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        library = self._library(correlation)
        if library.get(capture_id) is None:
            raise self._fail(
                "not_found", f"no published capture: {capture_id}", correlation
            )
        library.set_pinned(capture_id, pinned)
        return {"capture_id": capture_id, "pinned": pinned}

    async def _op_capture_unpin(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        return await self._op_capture_pin(arguments, correlation, pinned=False)

    async def _op_capture_delete(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        state = self._capture
        if state is not None and state["capture_id"] == capture_id:
            raise self._fail(
                "conflict",
                f"capture {capture_id} is in flight: stop it before deleting",
                correlation,
            )
        library = self._library(correlation)
        row = library.get(capture_id)
        if row is None:
            raise self._fail(
                "not_found", f"no published capture: {capture_id}", correlation
            )
        if row["pinned"]:
            raise self._fail(
                "conflict",
                f"capture {capture_id} is pinned; unpin it before deleting",
                correlation,
            )
        library.remove(capture_id)
        self._capture_outcomes.pop(capture_id, None)
        return {"capture_id": capture_id, "deleted": True}

    async def _op_artifact_read(
        self, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        event = self._event_dir(capture_id, correlation)
        manifest_path = event / "manifest.json"
        if not manifest_path.is_file():
            raise self._fail(
                "not_found", f"no published capture: {capture_id}", correlation
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        byte_length = int(manifest.get("byte_length", 0))
        offset = int(arguments["offset"])
        length = int(arguments["length"])
        if offset > byte_length:
            raise self._fail(
                "invalid_request",
                f"offset {offset} is beyond the artifact's end ({byte_length})",
                correlation,
            )
        serve = min(length, byte_length - offset)
        suffix = _PRIMARY_SUFFIXES.get(str(manifest.get("format", "")), ".data")
        with (event / f"{capture_id}{suffix}").open("rb") as primary:
            primary.seek(offset)
            data = primary.read(serve)
        return {
            "capture_id": capture_id,
            "artifact_id": str(manifest.get("artifact_id", "")),
            "offset": offset,
            "length": len(data),
            "data_base64": base64.b64encode(data).decode("ascii"),
        }

    def close(self) -> None:
        """Release host-owned resources: the capture library's root lock
        (the lifespan close-down's host half — the session's own adapter
        close is the lifespan's separate call). Idempotent."""
        library, self._capture_library = self._capture_library, None
        if library is not None:
            with contextlib.suppress(Exception):
                library.close()

    # --- the capture watcher (ruling 1: the host finalises, never the adapter)

    async def _watch_capture(self, state: dict[str, Any]) -> dict[str, Any]:
        """Poll the adapter task to its terminal state and settle the
        capture honestly.

        Cooperative adapters return at their bound on their own; this loop
        is the BACKSTOP: at a reached bound it grants a grace window, then
        cancels the operation context (the adapter's next transfer/append
        refuses). ``capture_stop``'s stop event short-circuits the grace —
        the operator asked. The terminal mapping is the locked ruling:
        envelope ok → finalise ``completed``; status/dispatch ``unknown`` →
        abort ``stop_unknown`` (an ambiguous capture is never published,
        A06); an error envelope → finalise the real bytes
        ``adapter_error``; an uncaught exception → abort
        ``adapter_exception`` — with the host's own cancel reason
        (``stopped``/``bound``) winning over the envelope's class when the
        host is the one that cancelled. A writer refusal at finalise aborts
        ``finalise_refused``.
        """
        task: asyncio.Task[dict[str, Any]] = state["task"]
        reason_pending: str | None = None
        grace_until: float | None = None
        forced_at: float | None = None
        # Progress coalescing (SW-26/NFR-Q3's frame budget): at most one
        # capture_progress row per window, and only when the staged total
        # actually moved.
        last_event_at = time.monotonic()
        last_event_bytes = 0
        while not task.done():
            await asyncio.wait({task}, timeout=_CAPTURE_POLL_S)
            if task.done():
                break
            now = time.monotonic()
            state["progress"] = self._capture_progress(state)
            if (
                state["progress"] > last_event_bytes
                and now - last_event_at >= _PROGRESS_WINDOW_S
            ):
                self.events.publish(
                    "capture_progress",
                    {
                        "capture_id": state["capture_id"],
                        "bytes": state["progress"],
                    },
                )
                last_event_at = now
                last_event_bytes = state["progress"]
            if state["stop_event"].is_set() and reason_pending is None:
                reason_pending = "stopped"
                state["context"].cancel()
                forced_at = now
                continue
            at_bound = (
                state["bound_bytes"] is not None
                and state["progress"] >= int(state["bound_bytes"])
            ) or (
                state["deadline"] is not None and now >= float(state["deadline"])
            )
            if at_bound and reason_pending is None:
                reason_pending = "bound"
                grace_until = now + _BOUND_GRACE_S
                continue
            if reason_pending == "bound" and grace_until is not None and now > grace_until:
                state["context"].cancel()
                forced_at = forced_at if forced_at is not None else now
            if forced_at is not None and now > forced_at + _STOP_SETTLE_MARGIN_S:
                # The adapter ignored even context cancellation: the task
                # itself is cancelled — the outcome is genuinely unknown.
                task.cancel()
                forced_at = now  # re-arm so this fires once
        try:
            envelope = task.result()
        except asyncio.CancelledError:
            return await self._abort_capture(
                state,
                "stop_unknown",
                detail="the adapter task was cancelled before reporting an outcome",
            )
        except Exception as exc:  # noqa: BLE001 - the uncaught bucket
            if reason_pending in ("stopped", "bound"):
                return await self._finalise_capture(state, reason_pending)
            return await self._abort_capture(
                state,
                "adapter_exception",
                detail=f"{type(exc).__name__}: {exc}",
            )
        status = str(envelope.get("status", ""))
        dispatch_state = str((envelope.get("error") or {}).get("dispatch_state", ""))
        if status == "ok":
            return await self._finalise_capture(state, "completed")
        if status == "unknown" or dispatch_state == "unknown":
            return await self._abort_capture(
                state,
                "stop_unknown",
                detail=str((envelope.get("error") or {}).get("message", "")),
            )
        if reason_pending in ("stopped", "bound"):
            return await self._finalise_capture(state, reason_pending)
        return await self._finalise_capture(state, "adapter_error")

    def _terminal_context(self, capture_id: str) -> HostOperationContext:
        """A fresh lifecycle context for the terminal path: the capture's
        own context may be cancelled (the bound backstop cancelled it), and
        the writer's tail-flush append honours cancellation — so finalising
        real bytes must not run under the cancelled context."""
        return HostOperationContext(
            f"capture-{capture_id}", timeout_ms=self._session.lifecycle_timeout_ms
        )

    async def _finalise_capture(
        self, state: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        capture_id = str(state["capture_id"])
        services = cast("_CaptureCapable", self._session.services)
        assert services is not None
        progress = self._capture_progress(state)
        writer_metadata: dict[str, Any] = {
            "format": state["format"],
            "started_at": state["started_at"],
        }
        if state["format"] == "waveform_f64le":
            # Ruling 3: the grid comes from the operator-declared start
            # arguments; the count is derived from the real staged bytes.
            writer_metadata["sample_count"] = progress // 8
            if state.get("interval") is not None:
                writer_metadata["sample_interval_s"] = state["interval"]
            if state.get("unit") is not None:
                writer_metadata["unit"] = state["unit"]
        try:
            manifest = await services.artifact_finalise(
                capture_id, writer_metadata, self._terminal_context(capture_id)
            )
        except (ValueError, RuntimeError, TimeoutError) as exc:
            # A refused finalise (a zero-byte capture, a partial trailing
            # sample, a writer refusal) aborts — nothing half-published.
            return await self._abort_capture(
                state, "finalise_refused", detail=str(exc)
            )
        metadata = dict(state["metadata"])
        metadata["stop_reason"] = reason
        with contextlib.suppress(Exception):
            # The index is acceleration; the disk is the truth. A library
            # refusal never fails the terminal path.
            library = self._library("")
            library.record_published(capture_id, manifest, metadata)
            library.set_stop_reason(capture_id, reason)
        row = self._row(
            capture_id,
            "published",
            state["started_at"],
            state["format"],
            metadata,
            byte_length=int(manifest.get("byte_length", 0)),
            sha256=str(manifest.get("sha256", "")),
            stop_reason=reason,
            progress_bytes=None,
        )
        self._capture_outcomes[capture_id] = row
        if self._capture is not None and self._capture["capture_id"] == capture_id:
            self._capture = None
        self.events.publish(
            "capture_stopped",
            {
                "capture_id": capture_id,
                "state": "published",
                "stop_reason": reason,
                "byte_length": row["byte_length"],
            },
        )
        return row

    async def _abort_capture(
        self, state: dict[str, Any], reason: str, detail: str | None = None
    ) -> dict[str, Any]:
        """Abort the capture: the services discard staging and REMOVE the
        un-finalised event directory (a capture that never published has
        nothing on disk), and the outcome row is session state."""
        capture_id = str(state["capture_id"])
        services = cast("_CaptureCapable | None", self._session.services)
        if services is not None:
            with contextlib.suppress(Exception):
                await services.artifact_abort(capture_id)
        row = self._row(
            capture_id,
            "aborted",
            state["started_at"],
            state["format"],
            state["metadata"],
            byte_length=None,
            sha256=None,
            stop_reason=reason,
            progress_bytes=None,
        )
        self._capture_outcomes[capture_id] = row
        if self._capture is not None and self._capture["capture_id"] == capture_id:
            self._capture = None
        self.events.publish(
            "capture_stopped",
            {
                "capture_id": capture_id,
                "state": "aborted",
                "stop_reason": reason,
                "byte_length": None,
            },
        )
        return row

    # --- adapter envelope handling -----------------------------------------

    async def _execute(
        self, verb: str, arguments: dict[str, Any], correlation: str
    ) -> dict[str, Any]:
        """Run one adapter envelope and map its outcome honestly."""
        try:
            envelope = await self._session.execute(verb, arguments)
        except ConformanceError as exc:
            raise self._fail(
                "unavailable",
                f"transport refused the exchange: {exc}",
                correlation,
            ) from exc
        except (TimeoutError, ConnectionError) as exc:
            raise self._fail(
                "not_ready", f"device not ready: {exc}", correlation
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the honest internal bucket
            raise SeamError(
                "internal_error",
                f"unexpected adapter failure: {exc}",
                correlation_id=correlation,
            ) from exc

        status = envelope.get("status")
        if status == "ok":
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise SeamError(
                    "internal_error",
                    "adapter returned no data object",
                    correlation_id=correlation,
                )
            return data
        error = envelope.get("error") or {}
        adapter_code = str(error.get("code", ""))
        code = _ADAPTER_CODE_MAP.get(adapter_code, "internal_error")
        raise self._fail(
            code,
            str(error.get("message", "adapter reported failure")),
            correlation,
            adapter={
                "status": status,
                "code": adapter_code,
                "dispatch_state": error.get("dispatch_state"),
            },
        )
