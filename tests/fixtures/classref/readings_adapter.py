"""Read-only synthetic OTDP adapter for class-fixture readings pages.

The scaffold's own adapter reads exactly one parameter (``voltage``); the
readings classes of the class sweep owe one tile per scalar variable, so
the fixture project swaps this generalisation in. The protocol is the
scaffold's own (identify over ``ID?``; one read per declared read-only
parameter over ``<name>?``), the transaction bounds come from the
descriptor's own transport settings, and nothing here speaks for a real
device. Synthetic exchanges only.
"""

import math


def create_plugin():
    return Plugin()


class Plugin:
    def __init__(self):
        self.services = None
        self.closed = False
        self._readable = {}
        self._max_bytes = 128

    async def open(self, descriptor, services, context):
        if self.services is not None or self.closed:
            raise RuntimeError("Use a fresh plugin instance")
        self.services = services
        settings = (descriptor.get("transport") or {}).get("settings") or {}
        self._max_bytes = int(settings.get("max_frame_bytes", 0)) or 128
        self._readable = {
            str(row.get("name")): row
            for row in descriptor.get("parameters", [])
            if row.get("access") in ("ro", "rw")
            and row.get("type") in ("float", "int")
        }

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
            return failure("UNSUPPORTED", "Only identify and parameter reads are supported")
        if (set(request) != {"operation_id", "verb", "arguments"}
                or not isinstance(operation_id, str) or not operation_id):
            return failure("INVALID_ARGUMENT", "Invalid envelope")
        expected = {} if verb == "identify" else None
        if verb == "read":
            name = str((request.get("arguments") or {}).get("parameter", ""))
            if name not in self._readable:
                return failure("INVALID_ARGUMENT", f"Unknown parameter: {name}")
        elif request["arguments"] != expected:
            return failure("INVALID_ARGUMENT", "Invalid arguments")
        try:
            remaining()
            await context.mark_dispatch_started()
            dispatched = True
            payload = b"ID?\n" if verb == "identify" else f"{name}?\n".encode()
            transaction = {
                "kind": "stream_exchange",
                "data": payload,
                "max_bytes": self._max_bytes,
                "termination": "lf",
                "exact_bytes": None,
            }
            response = await self.services.transfer(transaction, context)
            remaining()
            data = response["data"]
            if verb == "identify":
                if not isinstance(data, bytes) or not data.endswith(b"\n"):
                    raise ValueError("Incomplete frame")
                fields = data.decode("ascii").strip().split(",")
                if len(fields) != 4:
                    raise ValueError("Unexpected identity")
                parsed = {"manufacturer": fields[0], "model": fields[1],
                          "serial": fields[2], "firmware": fields[3],
                          "source": "device"}
            else:
                if not isinstance(data, bytes) or not data.endswith(b"\n"):
                    raise ValueError("Incomplete frame")
                value = float(data)
                if not math.isfinite(value):
                    raise ValueError("Nonfinite reading")
                unit = self._readable[name].get("unit", "")
                parsed = {"parameter": name, "value": value, "unit": unit,
                          "observed_at": self.services.utc_now(), "age_ms": 0,
                          "quality": "valid", "source": "device"}
            return {"operation_id": operation_id, "verb": verb,
                    "status": "ok", "data": parsed}
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
