# author: Stephen Eaton
"""Scripted adapter for the SDK dataset identity binding arms (issue #606).

Invented names only. A test copies this file over a scaffolded project's
``adapter.py`` before the load and fishes the loaded module out of
``sys.modules`` (the ``scripted_invoke_adapter`` precedent). The test then
writes PLANS: the steps the adapter runs inside ``execute`` for the invoke
verb, one plan per dispatch in entry order (the last plan serves every later
dispatch), so each arm states its scenario as data — where the adapter
publishes, which ids it claims, what it holds open and what it leaves
running after it returns.

Every knob is module state. ``reset()`` clears it all; call it after the
load, because a project loaded twice in one process keeps its first module.

The step vocabulary
-------------------
``("hold", name)``
    Signal ``ENTERED[name]``, then wait for ``RELEASE[name]``.
``("barrier", parties)``
    Wait until ``parties`` dispatches stand here at once.
``("remember",)``
    File this context under ``CONTEXTS[operation_id]``.
``("save",)``
    Make this context ``SAVED["context"]``.
``("rewrite", dataset_id)``
    Assign ``context.dataset_id``: the forgery the issue describes.
``("mutate_input", field, value)``
    Assign into the dispatched input object IN PLACE
    (``request["arguments"]["input"]``).
``("publish", key, dataset_id, context, [reading])``
    Call ``services.dataset_publish`` once and record the outcome under
    ``OUTCOMES[operation_id][key]``. ``dataset_id`` is ``"context"`` (read
    from the resolved context at call time) or a literal. ``context`` is
    ``"own"``, ``"saved"`` or ``("copy", operation_id, dataset_id)``: a
    shallow copy of this context under other ids. ``reading`` overrides the
    manifest's single value.
``("publish_foreign", key)``
    The same publication (own mint, own context) through
    ``FOREIGN_SERVICES`` instead of this adapter's services.
``("publish_cross",)``
    The forgery under overlap: rewrite this context's dataset id to the
    OTHER remembered operation's mint, publish a manifest that carries it,
    restore the id. The outcome lands under ``OUTCOMES[operation_id]
    ["cross"]``.
``("spawn", key)``
    Create a task that inherits this dispatch's context. It waits for
    ``release_orphan(key)``, then runs ``ORPHANS[key]`` and records under
    ``ORPHAN_OUTCOMES[key]``.
``("nested",)``
    Await ``NESTED()``: a second public dispatch the test supplies, made in
    this task's own context.
``("raise", message)``
    Raise ``RuntimeError``.
``("result", payload)``, ``("dataset_result", dataset_id)``,
``("echo_configuration",)``
    End the plan with this result payload. ``dataset_result`` answers a
    dataset-shaped manifest (the inline admission path). Without a result
    step the result is ``{}``.
"""

import asyncio
import copy

#: The manifest template every publication copies; ``dataset_id`` is filled
#: per step, never by the test.
MANIFEST = {}

#: One plan per dispatch, in entry order; the last plan serves every later
#: dispatch. A plan is a list of steps (the vocabulary above).
PLANS = []

#: The steps an orphan task runs once it is released, by key.
ORPHANS = {}

#: The services object ``publish_foreign`` publishes through.
FOREIGN_SERVICES = None

#: The zero-argument coroutine factory ``nested`` awaits.
NESTED = None

#: The receipt ``identify`` answers; it agrees with the scaffold descriptor.
IDENTITY = {
    "manufacturer": "SDK Example",
    "model": "demo",
    "serial": "SIM-0001",
    "firmware": "1.0.0",
    "source": "descriptor",
}

#: ``hold`` signals, by name.
ENTERED = {}
RELEASE = {}

#: The release event of each orphan task, by key.
ORPHAN_RELEASE = {}

#: ``barrier`` parties, by party count.
BARRIERS = {}

#: Every ``remember``-ed context, by operation id.
CONTEXTS = {}

#: The ``save``-d context (``SAVED["context"]``).
SAVED = {}

#: Publication outcomes of the dispatches: ``OUTCOMES[operation_id][key]``.
OUTCOMES = {}

#: Publication outcomes of the orphan tasks: ``ORPHAN_OUTCOMES[key][key]``.
ORPHAN_OUTCOMES = {}

#: Every invoke dispatch's arguments, in entry order.
ENTRIES = []

#: Every spawned orphan task, for the test to await.
TASKS = []


def reset():
    """Clear every knob (a project loaded twice keeps its first module)."""
    PLANS.clear()
    ORPHANS.clear()
    ENTERED.clear()
    RELEASE.clear()
    ORPHAN_RELEASE.clear()
    BARRIERS.clear()
    CONTEXTS.clear()
    SAVED.clear()
    OUTCOMES.clear()
    ORPHAN_OUTCOMES.clear()
    ENTRIES.clear()
    TASKS.clear()
    global FOREIGN_SERVICES, NESTED
    FOREIGN_SERVICES = None
    NESTED = None


def gate(name):
    """The test's handle on a ``hold`` step: ``(entered, release)``."""
    return _event(ENTERED, name), _event(RELEASE, name)


def release_orphan(key):
    """Let the orphan task ``key`` run its steps."""
    _event(ORPHAN_RELEASE, key).set()


def _next_plan():
    """The plan of the next dispatch: the head of the queue while more than
    one is queued, else the last plan, which serves every later dispatch."""
    if len(PLANS) > 1:
        return PLANS.pop(0)
    return PLANS[0] if PLANS else []


def _event(events, name):
    if name not in events:
        events[name] = asyncio.Event()
    return events[name]


def _manifest(dataset_id, reading=None):
    manifest = copy.deepcopy(MANIFEST)
    manifest["dataset_id"] = dataset_id
    if reading is not None:
        manifest["variables"][0]["values"] = [reading]
    return manifest


def _target(context, spec):
    """The context a publication is made under."""
    if spec == "own":
        return context
    if spec == "saved":
        return SAVED["context"]
    kind, operation_id, dataset_id = spec
    assert kind == "copy", spec
    forged = copy.copy(context)
    forged.operation_id = operation_id
    forged.dataset_id = dataset_id
    return forged


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
            return _ok(request, dict(IDENTITY))
        if verb == "invoke":
            ENTRIES.append(dict(request.get("arguments") or {}))
            outcomes = OUTCOMES.setdefault(str(context.operation_id), {})
            result = await self._run(_next_plan(), request, context, outcomes)
            return _ok(request, {
                "action_id": request["arguments"]["action_id"],
                "result": result,
            })
        return _fail(request, "UNSUPPORTED",
                     f"the identity adapter does not serve {verb!r}")

    async def _run(self, steps, request, context, outcomes):
        arguments = request.get("arguments") or {}
        for step in steps:
            kind, *args = step
            if kind == "hold":
                _event(ENTERED, args[0]).set()
                await _event(RELEASE, args[0]).wait()
            elif kind == "barrier":
                if args[0] not in BARRIERS:
                    BARRIERS[args[0]] = asyncio.Barrier(args[0])
                await BARRIERS[args[0]].wait()
            elif kind == "remember":
                CONTEXTS[str(context.operation_id)] = context
            elif kind == "save":
                SAVED["context"] = context
            elif kind == "rewrite":
                context.dataset_id = args[0]
            elif kind == "mutate_input":
                arguments["input"][args[0]] = args[1]
            elif kind == "publish":
                await self._publish(context, outcomes, *args)
            elif kind == "publish_foreign":
                await self._publish(context, outcomes, args[0], "context", "own",
                                    services=FOREIGN_SERVICES)
            elif kind == "publish_cross":
                await self._publish_cross(context, outcomes)
            elif kind == "spawn":
                TASKS.append(asyncio.create_task(self._orphan(args[0], context)))
            elif kind == "nested":
                await NESTED()
            elif kind == "raise":
                raise RuntimeError(args[0])
            elif kind == "result":
                return args[0]
            elif kind == "dataset_result":
                dataset_id = (
                    context.dataset_id if args[0] == "context" else args[0]
                )
                return _manifest(dataset_id)
            elif kind == "echo_configuration":
                configuration = dict(arguments["input"])
                return {
                    "configuration_id": configuration["configuration_id"],
                    "effective_configuration": configuration,
                }
            else:
                raise AssertionError(f"unknown plan step {step!r}")
        return {}

    async def _publish(self, context, outcomes, key, dataset_id, spec, *reading,
                       services=None):
        target = _target(context, spec)
        claimed = target.dataset_id if dataset_id == "context" else dataset_id
        manifest = _manifest(claimed, reading[0] if reading else None)
        if services is None:
            services = self._services
        try:
            await services.dataset_publish(manifest, target)
            outcomes[key] = "admitted"
        except ValueError as exc:
            outcomes[key] = f"refused: {exc}"

    async def _publish_cross(self, context, outcomes):
        own = context.dataset_id
        others = [
            saved
            for operation_id, saved in CONTEXTS.items()
            if operation_id != str(context.operation_id)
        ]
        assert len(others) == 1, "publish_cross needs one other remembered context"
        context.dataset_id = others[0].dataset_id
        try:
            # 9.9: the cross claim is a DIFFERENT manifest, so a host that
            # admits it makes the mint's own operation refuse as immutable.
            await self._publish(context, outcomes, "cross", "context", "own", 9.9)
        finally:
            context.dataset_id = own

    async def _orphan(self, key, context):
        await _event(ORPHAN_RELEASE, key).wait()
        request = {"arguments": {}}
        outcomes = ORPHAN_OUTCOMES.setdefault(key, {})
        await self._run(ORPHANS.get(key, []), request, context, outcomes)


def _ok(request, data):
    return {"operation_id": request["operation_id"], "verb": request["verb"],
            "status": "ok", "data": data}


def _fail(request, code, message, dispatch_state="not_dispatched"):
    return {"operation_id": request["operation_id"], "verb": request["verb"],
            "status": "error",
            "error": {"code": code, "message": message,
                      "dispatch_state": dispatch_state}}
