"""Scripted adapter for the #589 PR-2 arms: every answer comes from the
module-level SCRIPT the test rewrites per arm. Invented names only.

The conftest ``invoke_project_builder`` copies this file over a scaffolded
project's ``adapter.py``; the test then fishes the loaded module out of
``sys.modules`` and rewrites SCRIPT before connecting.
"""

import time

SCRIPT = {
    # None -> the default string receipt; a dict -> that receipt verbatim.
    "identify": None,
    # None -> {action_id, result: {}}; a dict -> that result payload;
    # {"__data__": {...}} -> that data envelope verbatim (the result-gate
    # arms); {"__error__": {...}} -> that failure envelope verbatim.
    "invoke": None,
    # None -> {"acknowledged": true}; a dict -> that receipt verbatim.
    "reset": None,
}

# "__deadline__" assigned to SCRIPT["invoke"] makes the adapter answer the
# measured context slack, so the deadline arm observes which budget minted
# the operation context.


def create_plugin():
    return _ScriptedAdapter()


class _ScriptedAdapter:
    def __init__(self):
        self._services = None

    async def open(self, descriptor, services, context):
        self._services = services

    async def close(self, context):
        self._services = None

    async def execute(self, request, context):
        verb = request.get("verb")
        if verb == "identify":
            # The default receipt agrees with the scaffold descriptor's
            # declared identity (the establishment cross-check compares them).
            data = dict(SCRIPT["identify"] or {
                "manufacturer": "SDK Example",
                "model": "demo",
                "serial": "SIM-0001",
                "firmware": "1.0.0",
                "source": "descriptor",
            })
            return _ok(request, data)
        if verb == "invoke":
            answer = SCRIPT["invoke"]
            if isinstance(answer, dict) and "__error__" in answer:
                return {"operation_id": request["operation_id"],
                        "verb": verb, **answer["__error__"]}
            if isinstance(answer, dict) and "__data__" in answer:
                return _ok(request, dict(answer["__data__"]))
            if answer == "__deadline__":
                slack_ms = (context.deadline_monotonic - time.monotonic()) * 1000.0
                return _ok(request, {
                    "action_id": request["arguments"]["action_id"],
                    "result": {"deadline_slack_ms": round(slack_ms, 3)},
                })
            result = {} if answer is None else dict(answer)
            return _ok(request, {
                "action_id": request["arguments"]["action_id"],
                "result": result,
            })
        if verb == "reset":
            data = ({"acknowledged": True} if SCRIPT["reset"] is None
                    else dict(SCRIPT["reset"]))
            return _ok(request, data)
        return _fail(request, "UNSUPPORTED",
                     f"the scripted adapter does not serve {verb!r}")


def _ok(request, data):
    return {"operation_id": request["operation_id"], "verb": request["verb"],
            "status": "ok", "data": data}


def _fail(request, code, message, dispatch_state="not_dispatched"):
    return {"operation_id": request["operation_id"], "verb": request["verb"],
            "status": "error",
            "error": {"code": code, "message": message,
                      "dispatch_state": dispatch_state}}
