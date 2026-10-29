# author: Stephen Eaton
"""Read/identify adapter over the FTDI common control surface.

The adapter reaches its transport ONLY through the pinned contract's one
provider kind and the generic section 8.1 stream kinds — the nine-kind
surface the live provider transport serves. ``decode_status`` is imported
BY NAME so a suite mutation of the decode is a single-point change of the
adapter's transport-relevant code (the replay fixture's own posture).
"""
import math

from . import protocol as proto
from .protocol import decode_status


def create_plugin():
    return Plugin()


class Plugin:
    def __init__(self):
        self.services = None
        self.closed = False
        self.identity = None

    async def open(self, descriptor, services, context):
        if self.services is not None or self.closed:
            raise RuntimeError("Use a fresh plugin instance")
        self.services = services
        self.identity = descriptor.get("identity", {})

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
            return failure("UNSUPPORTED", "Only identify and read are supported")
        if set(request) != {"operation_id", "verb", "arguments"}:
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        if verb == "read" and request["arguments"] != {"parameter": "line_status"}:
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

    async def _identify(self, context, remaining):
        """The bring-up conversation: the init chain over the provider kind,
        then the bitstream chunk over the data pipe, then the DONE-gated pin
        poll."""
        await self.services.transfer(proto.reset_device(), context)
        await self.services.transfer(proto.purge_rx(), context)
        await self.services.transfer(proto.set_latency(), context)
        await self.services.transfer(proto.set_baud(), context)
        await self.services.transfer(proto.set_bitmode(), context)
        idle = await self.services.transfer(proto.read_pins(), context)
        remaining()
        if idle["data"][0] != proto.PINS_IDLE:
            raise ValueError("Pins did not read idle before the bitstream")
        await self.services.transfer(
            proto.stream_send(proto.BITSTREAM_CHUNK), context)
        done = await self.services.transfer(proto.read_pins(), context)
        remaining()
        if not done["data"][0] & proto.DONE_MASK:
            raise ValueError("Bring-up did not gate on DONE")
        return {
            "manufacturer": self.identity.get("manufacturer", ""),
            "model": self.identity.get("model", ""),
            "firmware": "1.0",
        }

    async def _read(self, context, remaining):
        """One reading: the status exchange over the data pipe."""
        reply = await self.services.transfer(proto.status_exchange(), context)
        remaining()
        return {"parameter": "line_status",
                "value": decode_status(reply["data"]),
                "unit": "count",
                "observed_at": self.services.utc_now(), "age_ms": 0,
                "quality": "valid", "source": "device"}

    async def next_event(self, subscription_id, context):
        return None

    async def close(self, context):
        if self.closed:
            return
        if self.services is not None:
            await self.services.close_transport(context)
        self.closed = True
