"""The seam event bus (I2c §4.2): one append-only order for every surface.

The seam is the only mutation path, so it is also the only publisher. Two
families ride the bus: the state-change operations themselves (connect,
disconnect, stage, apply, preset, the reload events) and ``refused`` —
every seam-exit refusal, whichever family it takes (unknown operation,
declared-but-deferred, argument validation, adapter-reported, and the
reload family's own guard and load refusals, which raise outside
``call()`` and publish themselves). Authoring tool refusals over document
edits are NOT seam operations and do not ride. Ids are monotonic and
gap-free (STO-2's spirit in-process): the counter and the append happen
under one lock, so concurrent callers can never observe a hole, and
``after(cursor)`` is therefore a pure slice.

The bus is process-lifetime and never evicts: ``events_get`` and the SSE
stream serve the whole sequence, and a watcher that reconnects with its
last id never misses a row. ``data`` is always a JSON object so the
catalogue's result schema can state it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SeamEvent:
    """One published row."""

    id: int
    kind: str
    data: dict[str, Any]

    def row(self) -> dict[str, Any]:
        """The wire shape ``events_get`` and SSE carry."""
        return {"id": self.id, "kind": self.kind, "data": self.data}


class EventBus:
    """Append-only, lock-guarded, monotonic gap-free ids from 1."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[SeamEvent] = []

    def publish(self, kind: str, data: dict[str, Any]) -> int:
        """Append one event; return its id."""
        if not kind:
            raise ValueError("standalone_event_kind_empty")
        with self._lock:
            # ids are 1-based and the list is append-only, so the next id
            # is always len+1 and after(cursor) is always a slice — the
            # gap-free property is structural, not emergent.
            event = SeamEvent(len(self._events) + 1, kind, dict(data))
            self._events.append(event)
            return event.id

    def after(self, cursor: int) -> list[dict[str, Any]]:
        """Every row with ``id > cursor``, in order."""
        with self._lock:
            if cursor < 0:
                cursor = 0
            # id == index + 1, so rows beyond the cursor start at index
            # ``cursor``; a cursor past the end serves nothing.
            return [event.row() for event in self._events[cursor:]]

    def last_id(self) -> int:
        """The newest id (0 when nothing has been published)."""
        with self._lock:
            return len(self._events)
