# author: Stephen Eaton
"""Read-write synthetic OTDP adapter over binary frames; qualify a real
device separately. The capture verb streams fixed-size binary sample
frames received with ``exact_bytes`` into the host's capture services —
cooperative, honouring its bound, the lifecycle rulings assume."""
import math

from .protocol import (
    SAMPLE_FRAME_BYTES,
    capture_frame,
    drain,
    identify_frame,
    parse_ack,
    parse_identity,
    parse_sample,
    read_frame,
    recv_frame,
    send_frame,
    write_frame,
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
        if verb not in ("identify", "read", "write", "capture"):
            return failure(
                "UNSUPPORTED",
                "Only identify, sample read, sample write and capture are supported",
            )
        if (set(request) != {"operation_id", "verb", "arguments"}
                or not isinstance(operation_id, str) or not operation_id):
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        if verb == "identify":
            expected = {}
        elif verb == "read":
            expected = {"parameter": "sample_avg"}
        elif verb == "write":
            expected = {"parameter": "sample_avg", "value": 3.0}
        else:
            expected = None
        if verb != "capture" and request["arguments"] != expected:
            return failure("INVALID_ARGUMENT", "Invalid arguments")
        if verb == "write":
            arguments = request["arguments"]
            value = arguments.get("value")
            if (set(arguments) != {"parameter", "value"}
                    or arguments.get("parameter") != "sample_avg"
                    or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0.0 <= value <= 5.0):
                return failure("INVALID_ARGUMENT", "Invalid write arguments")
        if verb == "capture":
            arguments = request["arguments"]
            if (not isinstance(arguments.get("capture_id"), str)
                    or not arguments.get("capture_id")):
                return failure("INVALID_ARGUMENT", "Invalid capture arguments")
        try:
            remaining()
            await context.mark_dispatch_started()
            dispatched = True
            # The drain idiom before every command: unsolicited status
            # frames are consumed deterministically, then the quiet line
            # ends the drain (the guide's telemetry-drain pattern).
            await drain(self.services, context)
            if verb == "identify":
                await self.services.transfer(send_frame(identify_frame()), context)
                reply = await self.services.transfer(recv_frame(), context)
                remaining()
                data = parse_identity(reply["data"])
            elif verb == "read":
                await self.services.transfer(send_frame(read_frame()), context)
                reply = await self.services.transfer(recv_frame(), context)
                remaining()
                data = {"parameter": "sample_avg",
                        "value": parse_sample(reply["data"]), "unit": "V",
                        "observed_at": self.services.utc_now(), "age_ms": 0,
                        "quality": "valid", "source": "device"}
            elif verb == "write":
                await self.services.transfer(
                    send_frame(write_frame(request["arguments"]["value"])), context)
                reply = await self.services.transfer(recv_frame(), context)
                remaining()
                if not parse_ack(reply["data"]):
                    return failure("DEVICE_REJECTED", "Device rejected the setpoint",
                                   True)
                data = {"parameter": "sample_avg",
                        "value": request["arguments"]["value"], "unit": "V",
                        "observed_at": self.services.utc_now(), "age_ms": 0,
                        "quality": "valid", "source": "device"}
            else:
                data = await self._capture(request, context, remaining)
            return {"operation_id": operation_id, "verb": verb, "status": "ok", "data": data}
        except TimeoutError:
            return failure("TIMEOUT", "Deadline or cancellation", dispatched)
        except ConnectionError:
            return failure("TRANSPORT_ERROR", "Connection lost", dispatched)
        except (ValueError, KeyError, TypeError):
            return failure("PROTOCOL_ERROR", "Invalid device response", dispatched)
        except RuntimeError:
            return failure("INTERNAL_ERROR", "Host resource or internal failure", dispatched)

    async def _capture(self, request, context, remaining):
        """Stream fixed-size binary sample frames into the capture services.

        The declared sample count is served exactly: ``count`` samples at
        two float64 samples per 16-byte frame, every frame received with
        ``exact_bytes`` (precedence over the terminator) and appended.
        """
        arguments = request["arguments"]
        count = int(arguments.get("count", 0))
        if count < 1 or count % 2:
            raise ValueError("Capture count must be a positive even sample count")
        frames = count // 2
        await self.services.transfer(send_frame(capture_frame(frames)), context)
        capture_id = arguments["capture_id"]
        received = bytearray()
        for _ in range(frames):
            reply = await self.services.transfer(
                recv_frame(max_bytes=SAMPLE_FRAME_BYTES, exact=SAMPLE_FRAME_BYTES),
                context,
            )
            remaining()
            frame = reply["data"]
            if len(frame) != SAMPLE_FRAME_BYTES:
                raise ValueError("Short sample frame")
            received += frame
            await self.services.artifact_append(capture_id, frame, context)
        return {"frames": frames, "byte_length": len(received)}

    async def next_event(self, subscription_id, context):
        return None

    async def close(self, context):
        if self.closed:
            return
        if self.services is not None:
            await self.services.close_transport(context)
        self.closed = True
