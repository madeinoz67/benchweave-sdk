"""The nine baseline scenarios, expressed through the live pipeline.

PRD 12 Q4 (ruled 2026-10-01): there is no separate preview tool — the
standalone host IS the author's preview. The old React preview showed the
nine generated presentation documents (``benchweave_sdk.fixtures.generate_baselines``
rows); this module gives those states a live-pipeline expression:

- the definitions ship as data (ids and titles verbatim from the baseline
  rows; the baseline-set parity is pinned by test against the SDK's own
  ``BASELINE_IDS``);
- the transfer scripts are DERIVED per plugin from the descriptor's own
  declarations — ``mock_exchanges``' precedent: the host invents no
  envelope (A02's posture), so a plugin from anywhere gets its scenario
  pages without any host knowledge of that plugin;
- :class:`ScenarioAdapter` is a host-shipped adapter speaking the scenario
  protocol over the scripted transport. The author's own adapter is never
  imported in scenario mode — it cannot express these states at all: the
  scaffold template hardcodes quality ``valid``, so no transfer script can
  drive ``stale``/``critical``/``trip`` through it (the §1 root cause, and
  the reason this adapter exists). A broken author adapter therefore does
  not blind the author either (§4.5 composes: the loader's degraded state
  still serves all nine states).

The scenario protocol (ASCII, LF-terminated — the scaffold protocol's
line discipline):

- establishment, only when the descriptor declares ``identify``:
  ``ID?\\n`` → ``<manufacturer>,<model>,<serial>,<firmware>\\n`` — every
  field derived from the descriptor's own identity and transport blocks
  (the serial is the connection key; the firmware is the first supported
  entry);
- read: ``R:<parameter>\\n`` → ``<value>,<quality>\\n`` (an empty value
  carries no reading), or ``!rejected\\n`` when the scripted device
  refuses the exchange — the adapter reports that frame as a
  ``DEVICE_REJECTED`` envelope with ``dispatch_state: dispatched`` (it
  transmitted and the device answered no).

Scenario-by-scenario translation (what the page shows): ``normal`` →
value + quality ``valid``; ``loading`` → value absent + ``loading``;
``stale`` → ``stale`` (device-declared quality, rendered verbatim — the
computed staleness verdict is I2's D-B2 work, a separate channel, never
laundered); ``disconnected`` → the establishment exchange refuses, connect
fails ``not_ready``, the page renders the refused state (through the
pipeline, disconnected IS a refused connection — the honest negative);
``warning``/``critical``/``trip`` → in-range value + the state's quality
string; ``recovery`` → ``recovering``; ``request-rejected`` → the read
path yields the dispatched device rejection (SW-12 distinctness — the
adapter's code rides the refusal verbatim).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from .session import LoadedPlugin, PluginLoadError, PluginSession
from .transport import LoopingMockHost


@dataclass(frozen=True, slots=True)
class ScenarioState:
    """One baseline state's policy over the readable parameters.

    The policy says, per readable parameter: what quality string the
    device reports, whether the value is present, and whether the
    exchange is refused.
    """

    id: str
    title: str
    #: The device-declared quality string served on reads ("" when the
    #: state serves no readings at all).
    quality: str
    #: Whether the read response carries a value (``loading`` does not).
    value_present: bool
    #: The state refuses the establishment (``disconnected``).
    establishment_refused: bool
    #: The scripted device answers every read with a rejection frame.
    reads_rejected: bool


#: The nine baseline scenarios, in ``generate_baselines``' own order. The
#: ids and titles are the baseline rows verbatim; the qualities are the
#: DEVICE-declared strings the live pipeline serves (the presentation
#: model's ``simulated`` label is the preview's channel, not a device
#: quality — ``source: scenario`` carries that fact here instead).
SCENARIOS: tuple[ScenarioState, ...] = (
    ScenarioState("normal", "Normal", "valid", True, False, False),
    ScenarioState("loading", "Loading", "loading", False, False, False),
    ScenarioState("stale", "Stale", "stale", True, False, False),
    ScenarioState("disconnected", "Disconnected", "", False, True, False),
    ScenarioState("warning", "Warning", "warning", True, False, False),
    ScenarioState("critical", "Critical", "critical", True, False, False),
    ScenarioState("trip", "Protective trip", "trip", True, False, False),
    ScenarioState("recovery", "Recovery", "recovering", True, False, False),
    ScenarioState("request-rejected", "Request rejected", "", False, False, True),
)

_SCENARIOS_BY_ID: dict[str, ScenarioState] = {row.id: row for row in SCENARIOS}


def state(scenario_id: str) -> ScenarioState:
    """The scenario definition for ``scenario_id`` (prefixed refusal)."""
    row = _SCENARIOS_BY_ID.get(scenario_id)
    if row is None:
        raise PluginLoadError(f"standalone_scenario_unknown: {scenario_id}")
    return row


class ScenarioSelection:
    """The current scenario id — host state the device page can switch.

    Switching mutates only the NEXT connection's script (the M1 fold's
    per-connection services): a live connection keeps the transport it
    opened with, and the swap takes effect on reconnect, honestly.
    """

    def __init__(self, scenario_id: str) -> None:
        self._id = ""
        self.select(scenario_id)

    @property
    def current(self) -> str:
        """The selected scenario id."""
        return self._id

    def select(self, scenario_id: str) -> None:
        """Switch the selection; unknown ids refuse with a prefix."""
        self._id = state(scenario_id).id


def _frame_bound(descriptor: dict[str, Any]) -> int:
    """The descriptor's own frame bound (``mock_exchanges``' reading)."""
    settings = descriptor.get("transport", {}).get("settings", {})
    return int(settings.get("max_frame_bytes", 0)) or 128


def _transaction(descriptor: dict[str, Any], payload: bytes) -> dict[str, Any]:
    return {
        "kind": "stream_exchange",
        "data": payload,
        "max_bytes": _frame_bound(descriptor),
        "termination": "lf",
        "exact_bytes": None,
    }


def _line(*fields: str) -> bytes:
    """Render one protocol line, refusing fields the grammar cannot carry."""
    for field in fields:
        if "," in field or "\n" in field:
            raise PluginLoadError(
                f"standalone_scenario_script: scenario value {field!r} is not "
                "representable in the ASCII line protocol"
            )
    try:
        return (",".join(fields) + "\n").encode("ascii")
    except UnicodeEncodeError as exc:
        raise PluginLoadError(
            f"standalone_scenario_script: scenario line is not ASCII: {exc}"
        ) from exc


def canonical_value(parameter: dict[str, Any]) -> bool | int | float | str:
    """The scenario's value for one parameter, from its own declaration.

    Midpoint of the declared ``range`` for numeric parameters (an int
    parameter keeps an int: the largest int not exceeding the midpoint);
    otherwise the type-canonical value — ``generate_baselines``'
    ``_synthetic_value`` vocabulary keyed on the descriptor's own type
    names (an enum parameter reads its first declared value).
    """
    declared_type = str(parameter.get("type", ""))
    bounds = parameter.get("range")
    if declared_type in ("float", "int") and isinstance(bounds, list) and len(bounds) == 2:
        midpoint = (float(bounds[0]) + float(bounds[1])) / 2
        return int(midpoint) if declared_type == "int" else midpoint
    if declared_type == "enum":
        enum_values = parameter.get("enum_values")
        if isinstance(enum_values, list) and enum_values:
            return str(enum_values[0])
        return "simulated"
    values: dict[str, bool | int | float | str] = {
        "float": 0.0,
        "int": 0,
        "bool": False,
        "string": "simulated",
    }
    return values.get(declared_type, "simulated")


def _identity_fields(descriptor: dict[str, Any]) -> list[str]:
    identity = descriptor.get("identity", {})
    firmware = identity.get("supported_firmware")
    return [
        str(identity.get("manufacturer", "")),
        str(identity.get("model", "")),
        str(descriptor.get("transport", {}).get("connection_key", "")),
        str(firmware[0]) if isinstance(firmware, list) and firmware else "unknown",
    ]


def scenario_exchanges(
    plugin: LoadedPlugin, scenario_id: str
) -> list[tuple[dict[str, Any], dict[str, Any] | Exception]]:
    """Derive the scenario transfer script from the plugin's declarations.

    Demand order is establishment (when ``identify`` is declared) then one
    read exchange per readable parameter, in the descriptor's own order —
    the order the readings page reads them. ``disconnected`` refuses the
    establishment and scripts nothing beyond it (there is no conversation
    to serve); a plugin without ``identify`` has no establishment to
    refuse, so every read exchange refuses instead — the page renders the
    same refused state either way.
    """
    scenario = state(scenario_id)
    descriptor = plugin.descriptor
    identify_declared = "identify" in descriptor.get("capabilities", [])
    script: list[tuple[dict[str, Any], dict[str, Any] | Exception]] = []
    if identify_declared:
        request = _transaction(descriptor, b"ID?\n")
        if scenario.establishment_refused:
            script.append((request, ConnectionError("scenario: device absent")))
        else:
            script.append((request, {"data": _line(*_identity_fields(descriptor))}))
    for parameter in plugin.readable_parameters:
        if scenario.establishment_refused and identify_declared:
            break
        name = str(parameter.get("name", ""))
        request = _transaction(descriptor, f"R:{name}\n".encode("ascii"))
        if scenario.establishment_refused:
            script.append((request, ConnectionError("scenario: device absent")))
        elif scenario.reads_rejected:
            script.append((request, {"data": b"!rejected\n"}))
        else:
            value_text = (
                _render(canonical_value(parameter)) if scenario.value_present else ""
            )
            script.append((request, {"data": _line(value_text, scenario.quality)}))
    if not script:
        raise PluginLoadError(
            f"standalone_scenario_script: {plugin.package} declares nothing the "
            f"scenario {scenario_id} could serve"
        )
    return script


def _render(value: bool | int | float | str) -> str:
    """Render a canonical value as the protocol's value text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _parse(parameter: dict[str, Any], text: str) -> bool | int | float | str | None:
    """Parse the protocol's value text back per the declared type."""
    if text == "":
        return None
    declared_type = str(parameter.get("type", ""))
    if declared_type == "float":
        return float(text)
    if declared_type == "int":
        return int(text)
    if declared_type == "bool":
        if text not in ("true", "false"):
            raise ValueError(f"not a bool frame: {text!r}")
        return text == "true"
    return text


class ScenarioAdapter:
    """The host-shipped adapter that speaks the scenario protocol.

    The SDK ``Adapter`` lifecycle, re-implemented host-side in the scaffold
    adapter's own shape (REG-1: fresh instance per session, ``open`` free of
    device I/O, one operation per context, idempotent-tolerant ``close``).
    Every envelope value — the identity fields, the unit, the value — comes
    from the descriptor; the QUALITY and any refusal come from the
    transport's script bytes. The device's answer, not this adapter, is
    what the page renders.
    """

    def __init__(self) -> None:
        self.descriptor: dict[str, Any] | None = None
        self.services: Any = None
        self.closed = False

    async def open(self, descriptor: dict[str, Any], services: Any, context: Any) -> None:
        if self.services is not None or self.closed:
            raise RuntimeError("Use a fresh adapter instance")
        self.descriptor = descriptor
        self.services = services

    async def execute(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
        verb = request.get("verb")
        operation_id = request.get("operation_id")
        dispatched = False

        def failure(code: str, message: str, uncertain: bool = False) -> dict[str, Any]:
            return {
                "operation_id": operation_id,
                "verb": verb,
                "status": "unknown" if uncertain else "error",
                "error": {
                    "code": code,
                    "message": message,
                    "dispatch_state": "unknown" if uncertain else "not_dispatched",
                },
            }

        descriptor = self.descriptor
        if descriptor is None or self.services is None or self.closed:
            return failure("INTERNAL_ERROR", "Scenario adapter is not open")
        if operation_id != context.operation_id:
            return failure("INVALID_ARGUMENT", "Context identity mismatch")
        if verb not in ("identify", "read"):
            return failure("UNSUPPORTED", "Only identify and scripted reads are supported")
        if set(request) != {"operation_id", "verb", "arguments"}:
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        parameters = {
            str(row.get("name")): row for row in descriptor.get("parameters", [])
        }
        name = str(request["arguments"].get("parameter", ""))
        if verb == "identify":
            if request["arguments"] != {}:
                return failure("INVALID_ARGUMENT", "Invalid arguments")
        elif request["arguments"] != {"parameter": name} or name not in parameters:
            return failure("INVALID_ARGUMENT", "Invalid arguments")

        deadline = context.deadline_monotonic
        if (
            not math.isfinite(deadline)
            or context.is_cancelled()
            or self.services.monotonic() >= deadline
        ):
            return failure("TIMEOUT", "Deadline or cancellation")
        try:
            await context.mark_dispatch_started()
            dispatched = True
            payload = (
                b"ID?\n" if verb == "identify" else f"R:{name}\n".encode("ascii")
            )
            response = await self.services.transfer(
                _transaction(descriptor, payload), context
            )
            if self.services.monotonic() >= deadline:
                return failure("TIMEOUT", "Deadline or cancellation", dispatched)
            raw = response.get("data")
            bound = _frame_bound(descriptor)
            if not isinstance(raw, bytes) or not raw.endswith(b"\n") or len(raw) > bound:
                raise ValueError("Incomplete scenario frame")
            frame = raw[:-1].decode("ascii")
            if verb == "identify":
                fields = frame.split(",")
                if len(fields) != 4:
                    raise ValueError("Unexpected identity frame")
                data: dict[str, Any] = {
                    "manufacturer": fields[0],
                    "model": fields[1],
                    "serial": fields[2],
                    "firmware": fields[3],
                    "source": "scenario",
                }
            elif frame == "!rejected":
                return {
                    "operation_id": operation_id,
                    "verb": verb,
                    "status": "error",
                    "error": {
                        "code": "DEVICE_REJECTED",
                        "message": "Device rejected the scripted request",
                        "dispatch_state": "dispatched",
                    },
                }
            else:
                value_text, _, quality = frame.rpartition(",")
                if not quality:
                    raise ValueError("Quality missing from the frame")
                data = {
                    "parameter": name,
                    "value": _parse(parameters[name], value_text),
                    "unit": parameters[name].get("unit"),
                    "observed_at": self.services.utc_now(),
                    "age_ms": 0,
                    "quality": quality,
                    "source": "scenario",
                }
            return {"operation_id": operation_id, "verb": verb, "status": "ok", "data": data}
        except TimeoutError:
            return failure("TIMEOUT", "Deadline or cancellation", dispatched)
        except ConnectionError:
            return failure("TRANSPORT_ERROR", "Connection lost", dispatched)
        except (ValueError, KeyError, TypeError):
            return failure("PROTOCOL_ERROR", "Invalid device response", dispatched)

    async def next_event(self, subscription_id: str, context: Any) -> dict[str, Any] | None:
        return None

    async def close(self, context: Any) -> None:
        if self.closed:
            return
        if self.services is not None:
            await self.services.close_transport(context)
        self.closed = True


def scenario_session(plugin: LoadedPlugin, selection: ScenarioSelection) -> PluginSession:
    """One session over the scenario adapter — the author's adapter is
    never imported (a broken adapter still serves all nine states)."""
    scenario_plugin = replace(plugin, adapter_factory=ScenarioAdapter)
    identify_declared = "identify" in plugin.descriptor.get("capabilities", [])
    return PluginSession(
        scenario_plugin,
        lambda: LoopingMockHost(
            scenario_exchanges(plugin, selection.current),
            establishment=1 if identify_declared else 0,
        ),
    )
