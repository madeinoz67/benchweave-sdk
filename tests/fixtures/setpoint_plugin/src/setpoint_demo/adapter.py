"""Read-write synthetic OTDP adapter; qualify a real device separately."""
import math

from .protocol import parse_ack, parse_identity, parse_limit, transaction


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
        if verb not in ("identify", "read", "write"):
            return failure("UNSUPPORTED", "Only identify, limit read and limit write are supported")
        if (set(request) != {"operation_id", "verb", "arguments"}
                or not isinstance(operation_id, str) or not operation_id):
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        if verb == "identify":
            expected = {}
        elif verb == "read":
            expected = {"parameter": "current_limit"}
        else:
            expected = {"parameter": "current_limit", "value": 2.5}
        if verb != "write" and request["arguments"] != expected:
            return failure("INVALID_ARGUMENT", "Invalid arguments")
        if verb == "write":
            arguments = request["arguments"]
            value = arguments.get("value")
            if (set(arguments) != {"parameter", "value"}
                    or arguments.get("parameter") != "current_limit"
                    or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0.0 <= value <= 5.0):
                return failure("INVALID_ARGUMENT", "Invalid write arguments")
        try:
            remaining()
            await context.mark_dispatch_started()
            dispatched = True
            if verb == "write":
                exchange = transaction("write", request["arguments"]["value"])
            else:
                exchange = transaction(verb)
            response = await self.services.transfer(exchange, context)
            remaining()
            if verb == "identify":
                data = parse_identity(response["data"])
            elif verb == "read":
                data = {"parameter": "current_limit",
                        "value": parse_limit(response["data"]), "unit": "A",
                        "observed_at": self.services.utc_now(), "age_ms": 0,
                        "quality": "valid", "source": "device"}
            else:
                if not parse_ack(response["data"]):
                    return failure("DEVICE_REJECTED", "Device rejected the setpoint",
                                   True)
                data = {"parameter": "current_limit",
                        "value": request["arguments"]["value"], "unit": "A",
                        "observed_at": self.services.utc_now(), "age_ms": 0,
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
