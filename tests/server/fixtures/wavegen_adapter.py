"""A capture-capable fixture adapter (an invented plugin; issue #285 tests).

Copied verbatim into a scaffolded project's ``src/<package>/adapter.py`` by
the capture lifecycle tests. ``identify`` answers over the transport; the
capture verb streams little-endian doubles through ``artifact_append`` and
is COOPERATIVE — it honours context cancellation and returns at its bound,
exactly the contract the host lifecycle rulings assume. The per-project
``behaviour.json`` (read on every capture) selects the mode a test needs:

- ``ok``      — append ``count`` doubles, return ok (the happy path)
- ``slow``    — the same, with a 20 ms pause per sample (stop-mid-flight)
- ``linger``  — append ``count`` doubles, then wait cancelled (the bound
                watchdog's backstop: a device that never returns on its own)
- ``stubborn_ok`` — append ``count`` doubles, ignore cancellation for
                ``stubborn_s`` (0.6 s), then return ok anyway (the host
                asked; the adapter answered ok regardless)
- ``overrun`` — append ``count`` then two more ``count`` lots at 50 ms a
                sample, ignoring the bound's cancellation, then return ok
                (declared N, staged 3N)
- ``zombie``  — absorb every cancellation and outlive the host's stop
                discipline for ``stubborn_s`` (5 s), then give up — the
                wedge shape (the host's stop-timeout escape)
- ``unknown`` — append, then return a status/dispatch ``unknown`` envelope
- ``error``   — append, then return an error envelope
- ``silent``  — return ok with zero appends (publishes nothing)
- ``raise``   — blow up mid-capture (the uncaught-exception bucket)

``default_count`` supplies the sample count when the start arguments carry
a duration bound instead of a count.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from pathlib import Path
from typing import Any

_ID_REQUEST = b"ID?\n"
_ID_REPLY_FIELDS = ("manufacturer", "model", "serial", "firmware")


def create_plugin() -> Plugin:
    return Plugin()


class Plugin:
    def __init__(self) -> None:
        self.services: Any = None
        self.closed = False

    async def open(self, descriptor: Any, services: Any, context: Any) -> None:
        if self.services is not None or self.closed:
            raise RuntimeError("Use a fresh plugin instance")
        self.services = services

    def _behaviour(self) -> dict[str, Any]:
        try:
            payload = json.loads(
                Path(__file__).with_name("behaviour.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _ok(verb: str, operation_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation_id": operation_id,
            "verb": verb,
            "status": "ok",
            "data": data,
        }

    @staticmethod
    def _failure(
        verb: str,
        operation_id: str,
        code: str,
        message: str,
        dispatched: bool,
        *,
        uncertain: bool = False,
    ) -> dict[str, Any]:
        dispatch_state = (
            "unknown" if uncertain else ("dispatched" if dispatched else "not_dispatched")
        )
        return {
            "operation_id": operation_id,
            "verb": verb,
            "status": "unknown" if uncertain else "error",
            "error": {"code": code, "message": message, "dispatch_state": dispatch_state},
        }

    async def execute(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
        verb = request.get("verb")
        operation_id = request.get("operation_id")
        arguments = request.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        if self.services is None or self.closed:
            return self._failure(verb, operation_id, "INTERNAL_ERROR", "not open", False)
        try:
            if verb == "identify":
                await context.mark_dispatch_started()
                reply = await self.services.transfer(
                    {
                        "kind": "stream_exchange",
                        "data": _ID_REQUEST,
                        "max_bytes": 128,
                        "termination": "lf",
                        "exact_bytes": None,
                    },
                    context,
                )
                fields = reply["data"].decode("ascii").strip().split(",")
                identity = dict(zip(_ID_REPLY_FIELDS, fields, strict=False))
                return self._ok(verb, operation_id, identity)
            if verb in ("capture", "invoke"):
                return await self._run_capture(verb, operation_id, arguments, context)
            return self._failure(verb, operation_id, "UNSUPPORTED", f"verb {verb}", False)
        except TimeoutError:
            return self._failure(verb, operation_id, "TIMEOUT", "deadline or cancel", True)
        except ConnectionError:
            return self._failure(
                verb, operation_id, "TRANSPORT_ERROR", "connection lost", True
            )

    async def _run_capture(
        self,
        verb: str,
        operation_id: str,
        arguments: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        capture_id = str(arguments["capture_id"])
        behaviour = self._behaviour()
        mode = behaviour.get("mode", "ok")
        count = int(arguments.get("count") or behaviour.get("default_count", 8))
        await context.mark_dispatch_started()
        # The verb record: the descriptor-declared verb resolution tests
        # read it back to prove WHICH verb the host dispatched.
        try:
            with Path(__file__).with_name("verbs.jsonl").open("a") as log:
                log.write(json.dumps({"verb": verb, "capture_id": capture_id}) + "\n")
        except OSError:
            pass
        if mode == "silent":
            return self._ok(verb, operation_id, {"capture_id": capture_id, "appended": 0})
        if mode == "raise":
            raise RuntimeError("fixture adapter failed mid-capture")
        values = [float(index % 20) - 9.5 for index in range(count)]
        appended = 0
        for value in values:
            if context.is_cancelled():
                return self._failure(
                    verb, operation_id, "TIMEOUT", "cancelled mid-stream", True
                )
            await self.services.artifact_append(
                capture_id, struct.pack("<d", value), context
            )
            appended += 1
            if mode == "slow":
                await asyncio.sleep(0.02)
        if mode == "linger":
            while not context.is_cancelled():
                await asyncio.sleep(0.02)
            return self._failure(verb, operation_id, "TIMEOUT", "cancelled at bound", True)
        if mode == "stubborn_ok":
            deadline = time.monotonic() + float(behaviour.get("stubborn_s", 0.6))
            while time.monotonic() < deadline:
                try:
                    await asyncio.sleep(0.02)
                except asyncio.CancelledError:
                    continue
            return self._ok(verb, operation_id, {"capture_id": capture_id, "appended": appended})
        if mode == "overrun":
            for value in [float(index % 20) - 9.5 for index in range(count * 2)]:
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    continue
                await self.services.artifact_append(
                    capture_id, struct.pack("<d", value), context
                )
                appended += 1
            return self._ok(verb, operation_id, {"capture_id": capture_id, "appended": appended})
        if mode == "zombie":
            deadline = time.monotonic() + float(behaviour.get("stubborn_s", 5.0))
            while time.monotonic() < deadline:
                try:
                    await asyncio.sleep(0.02)
                except asyncio.CancelledError:
                    continue
            return self._failure(verb, operation_id, "TIMEOUT", "zombie gave up", True)
        if mode == "unknown":
            return self._failure(
                verb,
                operation_id,
                "INTERNAL_ERROR",
                "outcome uncertain after appends",
                True,
                uncertain=True,
            )
        if mode == "error":
            return self._failure(
                verb, operation_id, "DEVICE_REJECTED", "fixture rejected after appends", True
            )
        return self._ok(verb, operation_id, {"capture_id": capture_id, "appended": appended})

    async def next_event(self, subscription_id: Any, context: Any) -> None:
        return None

    async def close(self, context: Any) -> None:
        if self.closed:
            return
        if self.services is not None:
            await self.services.close_transport(context)
        self.closed = True
