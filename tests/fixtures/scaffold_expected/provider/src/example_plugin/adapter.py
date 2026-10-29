"""Read-only synthetic OTDP adapter over the FTDI common control surface.

The adapter reaches its transport ONLY through the pinned contract's one
provider kind and the generic section 8.1 stream kinds. Rehearsal without
hardware runs over the SDK's shipped driver double; serve the plugin with
`benchweave-sdk-server serve --transport ftdi --device <ftdi-url>` on a
bench (and `--record <path>` to capture a replay journal of the session)."""
import math

from .protocol import (
    BITSTREAM_CHUNK,
    DONE_BYTE,
    PINS_IDLE,
    decode_status,
    purge_rx,
    read_pins,
    reset_device,
    set_baud,
    set_bitmode,
    set_latency,
    status_exchange,
    stream_send,
)


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
            return failure("UNSUPPORTED", "Only identify and line-status read are supported")
        if (set(request) != {"operation_id", "verb", "arguments"}
                or not isinstance(operation_id, str) or not operation_id):
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        expected = {} if verb == "identify" else {"parameter": "line_status"}
        if request["arguments"] != expected:
            return failure("INVALID_ARGUMENT", "Invalid arguments")
        try:
            remaining()
            await context.mark_dispatch_started()
            dispatched = True
            if verb == "identify":
                data = await self._identify(context, remaining)
            else:
                data = await self._read(context, remaining)
            return {"operation_id": operation_id, "verb": verb, "status": "ok", "data": data}
        except TimeoutError:
            return failure("TIMEOUT", "Deadline or cancellation", dispatched)
        except ConnectionError:
            return failure("TRANSPORT_ERROR", "Connection lost", dispatched)
        except (ValueError, KeyError, TypeError):
            return failure("PROTOCOL_ERROR", "Invalid device response", dispatched)
        except RuntimeError:
            return failure("INTERNAL_ERROR", "Host resource or internal failure", dispatched)

    async def _identify(self, context, remaining):
        """The bring-up conversation: the init chain over the provider
        kind, then the bitstream chunk over the data pipe, then the
        DONE-gated pin poll."""
        services = self.services
        await services.transfer(reset_device(), context)
        await services.transfer(purge_rx(), context)
        await services.transfer(set_latency(), context)
        await services.transfer(set_baud(), context)
        await services.transfer(set_bitmode(), context)
        idle = await services.transfer(read_pins(), context)
        remaining()
        if idle["data"][0] != PINS_IDLE:
            raise ValueError("Pins did not read idle before the bitstream")
        await services.transfer(stream_send(BITSTREAM_CHUNK), context)
        done = await services.transfer(read_pins(), context)
        remaining()
        if done["data"][0] != DONE_BYTE:
            raise ValueError("Bring-up did not gate on DONE")
        return {"manufacturer": "SDK Example", "model": "demo",
                "firmware": "1.0.0", "source": "device"}

    async def _read(self, context, remaining):
        """One reading: the status exchange over the data pipe."""
        reply = await self.services.transfer(status_exchange(), context)
        remaining()
        return {"parameter": "line_status", "value": decode_status(reply["data"]),
                "unit": "count", "observed_at": self.services.utc_now(), "age_ms": 0,
                "quality": "valid", "source": "device"}

    async def next_event(self, subscription_id, context):
        return None

    async def close(self, context):
        if self.closed:
            return
        if self.services is not None:
            await self.services.close_transport(context)
        self.closed = True
