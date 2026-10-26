# author: Stephen Eaton
"""Read/identify/capture adapter over the reference-hid provider grammar.

The adapter reaches its transport ONLY through the provider's two
transaction kinds and the generic section 8.1 stream kinds — the same
nine-kind surface the replay transport serves. ``decode_status`` is
imported BY NAME so the suite's decode-inversion mutation (the B5 class)
is a true single-point change of the adapter's transport-relevant code."""
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
        if verb not in ("identify", "read", "capture"):
            return failure("UNSUPPORTED", "Only identify, read and capture are supported")
        if set(request) != {"operation_id", "verb", "arguments"}:
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        if verb == "read" and request["arguments"] != {"parameter": "bus_power"}:
            return failure("INVALID_ARGUMENT", "Invalid arguments")
        if verb == "capture":
            arguments = request["arguments"]
            if (not isinstance(arguments.get("capture_id"), str)
                    or not arguments.get("capture_id")):
                return failure("INVALID_ARGUMENT", "Invalid capture arguments")
        try:
            remaining()
            await context.mark_dispatch_started()
            dispatched = True
            if verb == "identify":
                data = await self._identify(context, remaining)
            elif verb == "read":
                data = await self._read(context, remaining)
            else:
                data = await self._capture(request, context, remaining)
            return {"operation_id": operation_id, "verb": verb, "status": "ok", "data": data}
        except TimeoutError:
            return failure("TIMEOUT", "Deadline or cancellation", dispatched)
        except ConnectionError:
            return failure("TRANSPORT_ERROR", "Connection lost", dispatched)
        except (ValueError, KeyError, TypeError):
            return failure("PROTOCOL_ERROR", "Invalid device response", dispatched)

    async def _identify(self, context, remaining):
        """The init chain: the provider handshake, then the bulk
        configuration load over the stream kinds."""
        await self.services.transfer(proto.hid_command(), context)
        await self.services.transfer(proto.hid_read(), context)
        remaining()
        await self.services.transfer(
            proto.stream_send(proto.config_blob()), context)
        ack = await self.services.transfer(
            proto.stream_receive(4, 3), context)
        remaining()
        if ack["data"] != b"\xc1\x00\x01":
            raise ValueError("Configuration was not acknowledged")
        return {
            "manufacturer": self.identity.get("manufacturer", ""),
            "model": self.identity.get("model", ""),
            "firmware": "1.0",
        }

    async def _read(self, context, remaining):
        """One reading: resync and drain the quiet line, poll, decode the
        status reply (the recorded read-reply grammar)."""
        await self.services.transfer(
            proto.stream_send(proto.resync_frame()), context)
        await self.services.transfer(proto.stream_receive(8, None), context)
        await self.services.transfer(
            proto.stream_send(proto.poll_frame()), context)
        reply = await self.services.transfer(proto.stream_receive(8, 4), context)
        remaining()
        return {"parameter": "bus_power",
                "value": decode_status(reply["data"]), "unit": "W",
                "observed_at": self.services.utc_now(), "age_ms": 0,
                "quality": "valid", "source": "device"}

    async def _capture(self, request, context, remaining):
        """Stream the declared sample frames into the capture services."""
        await self.services.transfer(
            proto.stream_send(proto.capture_frame(proto.SAMPLE_FRAMES)), context)
        capture_id = request["arguments"]["capture_id"]
        received = bytearray()
        for _ in range(proto.SAMPLE_FRAMES):
            reply = await self.services.transfer(
                proto.stream_receive(proto.SAMPLE_FRAME_BYTES,
                                     proto.SAMPLE_FRAME_BYTES),
                context)
            remaining()
            frame = reply["data"]
            if len(frame) != proto.SAMPLE_FRAME_BYTES:
                raise ValueError("Short sample frame")
            received += frame
            await self.services.artifact_append(capture_id, frame, context)
        await self.services.transfer(
            proto.stream_send(proto.capture_end_frame()), context)
        ack = await self.services.transfer(proto.stream_receive(4, 3), context)
        remaining()
        if ack["data"] != b"\xc1\x00\x04":
            raise ValueError("Capture was not acknowledged")
        return {"frames": proto.SAMPLE_FRAMES, "byte_length": len(received)}

    async def next_event(self, subscription_id, context):
        return None

    async def close(self, context):
        if self.closed:
            return
        if self.services is not None:
            await self.services.close_transport(context)
        self.closed = True
