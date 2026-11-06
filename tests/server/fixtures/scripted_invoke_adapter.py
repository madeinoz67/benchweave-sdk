"""Scripted adapter for the #589 PR-2/PR-3 arms: every answer comes from the
module-level SCRIPT the test rewrites per arm. Invented names only.

The conftest ``invoke_project_builder`` copies this file over a scaffolded
project's ``adapter.py``; the test then fishes the loaded module out of
``sys.modules`` and rewrites SCRIPT before connecting.

The PR-3 dataset modes (issue #589 §4): ``__dataset__`` answers a
measurement manifest built from the module-level DATASET template against
``context.dataset_id`` — the ruled inline path in miniature, the real
plugin's shape; ``__publish__`` calls the wrapped services'
``dataset_publish`` once per PUBLISH_QUEUE template; ``__lookup__`` calls
``dataset_lookup`` once per LOOKUP_IDS entry. Both service modes answer a
PLAIN (non-dataset-shaped) result naming each outcome, so the arms observe
the services boundary without triggering the inline admission themselves.
"""

import copy
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
#
# "__context__" (invoke or identify) answers the observed context dataset id
# beside the request's own operation id, so the mint arms observe what the
# adapter actually saw without shaping a manifest.
#
# "__dataset__" (invoke) answers a measurement manifest: a deep copy of the
# module-level DATASET template with ``dataset_id`` overwritten from
# ``context.dataset_id``.
#
# "__publish__" / "__lookup__" (invoke) exercise the dataset services members
# (PR-3's explicit surface) and answer each call's outcome.

#: The manifest template for ``__dataset__``; ``dataset_id`` is always
#: overwritten from the context (the host mints it, never the adapter).
DATASET = {}

#: Manifest templates for ``__publish__``; each publishes with
#: ``dataset_id`` forced from the context, like an honest adapter.
PUBLISH_QUEUE = []

#: Dataset ids for ``__lookup__``.
LOOKUP_IDS = []

#: Every verb this adapter executed, in order (the D6 arms prove a refusal
#: happened BEFORE any dispatch by reading it).
CALLS: list[str] = []


def create_plugin():
    return _ScriptedAdapter()


class _ScriptedAdapter:
    def __init__(self):
        self._services = None

    async def open(self, descriptor, services, context):
        self._services = services

    async def close(self, context):
        self._services = None

    @staticmethod
    def _default_identity():
        # The default receipt agrees with the scaffold descriptor's declared
        # identity (the establishment cross-check compares them).
        return {
            "manufacturer": "SDK Example",
            "model": "demo",
            "serial": "SIM-0001",
            "firmware": "1.0.0",
            "source": "descriptor",
        }

    async def execute(self, request, context):
        verb = request.get("verb")
        CALLS.append(str(verb))
        if verb == "identify":
            if SCRIPT["identify"] == "__context__":
                data = self._default_identity()
                data["observed_dataset_id"] = getattr(
                    context, "dataset_id", None
                )
                return _ok(request, data)
            data = dict(SCRIPT["identify"] or self._default_identity())
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
            if answer == "__context__":
                observed = getattr(context, "dataset_id", None)
                expected = "ds:" + str(request.get("operation_id"))
                return _ok(request, {
                    "action_id": request["arguments"]["action_id"],
                    "result": {
                        "observed_dataset_id": observed,
                        "expected_dataset_id": expected,
                        "mint_matches": observed == expected,
                    },
                })
            if answer == "__dataset__":
                manifest = copy.deepcopy(DATASET)
                manifest["dataset_id"] = getattr(context, "dataset_id", None)
                return _ok(request, {
                    "action_id": request["arguments"]["action_id"],
                    "result": manifest,
                })
            if answer == "__publish__":
                outcomes = []
                for template in PUBLISH_QUEUE:
                    manifest = copy.deepcopy(template)
                    manifest["dataset_id"] = getattr(
                        context, "dataset_id", None
                    )
                    try:
                        await self._services.dataset_publish(manifest, context)
                        outcomes.append("admitted")
                    except ValueError as exc:
                        outcomes.append(f"refused: {exc}")
                return _ok(request, {
                    "action_id": request["arguments"]["action_id"],
                    "result": {"publishes": outcomes},
                })
            if answer == "__lookup__":
                outcomes = []
                for dataset_id in LOOKUP_IDS:
                    try:
                        found = await self._services.dataset_lookup(
                            dataset_id, context
                        )
                        outcomes.append(
                            "found:" + str(found.get("dataset_id"))
                            if isinstance(found, dict)
                            else "found"
                        )
                    except ValueError as exc:
                        outcomes.append(f"refused: {exc}")
                return _ok(request, {
                    "action_id": request["arguments"]["action_id"],
                    "result": {"lookups": outcomes},
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
