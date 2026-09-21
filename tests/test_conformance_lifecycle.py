"""check_lifecycle: the quiet-subscription guard, and what MockHost([]) already refuses."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import pytest

from benchweave_sdk.conformance import check_lifecycle
from benchweave_sdk.testing import ConformanceError
from benchweave_sdk.validation import contract_documents


def _descriptor() -> dict[str, Any]:
    documents = contract_documents()
    matches = [key for key in documents if key.endswith("/examples/reference-psu.json")]
    assert len(matches) == 1, matches
    return deepcopy(documents[matches[0]])


class _QuietAdapter:
    def __init__(self) -> None:
        self.closed = 0

    async def open(self, descriptor: dict[str, Any], services: Any, context: Any) -> None:
        self.services = services

    async def execute(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
        raise AssertionError("the lifecycle check never executes an operation")

    async def next_event(self, subscription_id: str, context: Any) -> dict[str, Any] | None:
        return None

    async def close(self, context: Any) -> None:
        self.closed += 1


class _EventfulAdapter(_QuietAdapter):
    async def next_event(self, subscription_id: str, context: Any) -> dict[str, Any] | None:
        return {"subscription_id": subscription_id, "value": 1}


class _TransferringAdapter(_QuietAdapter):
    async def open(self, descriptor: dict[str, Any], services: Any, context: Any) -> None:
        await context.mark_dispatch_started()
        await services.transfer({"kind": "stream_exchange", "data": b"ID?"}, context)


def test_quiet_adapter_passes_and_is_closed_twice() -> None:
    """close is awaited again after the first: an adapter must tolerate a repeated close."""
    adapters: list[_QuietAdapter] = []

    def factory() -> _QuietAdapter:
        adapters.append(_QuietAdapter())
        return adapters[-1]

    asyncio.run(check_lifecycle(factory, _descriptor()))
    assert [adapter.closed for adapter in adapters] == [2]


def test_an_event_on_a_quiet_subscription_is_a_conformance_failure() -> None:
    with pytest.raises(ConformanceError, match="^A quiet subscription returned an event$"):
        asyncio.run(check_lifecycle(_EventfulAdapter, _descriptor()))


def test_device_io_during_open_is_refused_by_the_empty_script() -> None:
    """The harness hands open() a MockHost with no script, so any transfer is refused there.

    That is what enforces "open performs no device I/O": the later
    ``host.transfers`` checks in check_lifecycle cannot fire with an empty
    script, because the transfer never gets as far as being recorded.
    """
    refusal = "^Unexpected transfer: no scripted exchange remains$"
    with pytest.raises(ConformanceError, match=refusal):
        asyncio.run(check_lifecycle(_TransferringAdapter, _descriptor()))
