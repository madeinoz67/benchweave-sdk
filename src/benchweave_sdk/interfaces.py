"""Structural contracts, not an implementation or permission grant.

Optional capture methods are separated from the base transport and evidence services.
Profile/dataset extensions must follow the pinned extension contract.
"""

from __future__ import annotations

from typing import Any, Protocol


class OperationContext(Protocol):
    operation_id: str
    dataset_id: str | None
    deadline_monotonic: float

    def is_cancelled(self) -> bool: ...
    async def mark_dispatch_started(self) -> None: ...


class HostServices(Protocol):
    def monotonic(self) -> float: ...
    def utc_now(self) -> str: ...
    async def transfer(
        self, transaction: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]: ...
    async def close_transport(self, context: OperationContext) -> None: ...
    async def record_evidence(self, entry: dict[str, Any], context: OperationContext) -> None: ...


class CaptureServices(HostServices, Protocol):
    async def artifact_append(
        self, capture_id: str, data: bytes, context: OperationContext
    ) -> None: ...
    async def artifact_finalise(
        self, capture_id: str, metadata: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]: ...
    async def artifact_abort(self, capture_id: str) -> None: ...


class Adapter(Protocol):
    async def open(
        self, descriptor: dict[str, Any], services: HostServices, context: OperationContext
    ) -> None: ...
    async def execute(
        self, request: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]: ...
    async def next_event(
        self, subscription_id: str, context: OperationContext
    ) -> dict[str, Any] | None: ...
    async def close(self, context: OperationContext) -> None: ...
