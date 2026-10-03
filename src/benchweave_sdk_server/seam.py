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
import hashlib
import json
import time
import uuid
from importlib import metadata
from typing import TYPE_CHECKING, Any, cast

from benchweave_sdk.presentation import read_file, validate_preset
from benchweave_sdk.testing import ConformanceError

from . import catalogue
from .errors import SeamError
from .session import PluginSession

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

#: Adapter envelope error codes → interface codes (SW-12 distinctness kept:
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


def sdk_version() -> str:
    """The SDK version this host runs on, derived — never a literal."""
    try:
        return metadata.version("benchweave-sdk")
    except metadata.PackageNotFoundError:  # pragma: no cover - dev-checkout edge
        return "unknown"


class StandaloneSeam:
    """One seam over one adapter session; the surfaces are its adapters."""

    def __init__(self, session: PluginSession, *, transport_kind: str) -> None:
        self._session = session
        self._transport_kind = transport_kind
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
    ) -> dict[str, Any]:
        """Execute one catalogue operation; return its data or raise ``SeamError``."""
        correlation = self._correlation(correlation_id)
        row = catalogue.spec(operation)
        if row is None:
            raise self._fail(
                "invalid_request",
                f"unknown operation: {operation}",
                correlation,
                closed_catalogue=catalogue.deferred_operations() + catalogue.served_operations(),
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
        return cast(dict[str, Any], result)

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
