"""Structural contracts, not an implementation or permission grant.

Optional capture methods are separated from the base transport and evidence services.
Profile/dataset extensions must follow the pinned extension contract.
"""

from __future__ import annotations

from typing import Any, Protocol


class OperationContext(Protocol):
    """Per-operation identity, deadline, and cancellation state.

    The host supplies one context per operation. Adapters correlate
    request and result envelopes by ``operation_id`` and treat
    ``deadline_monotonic`` as the expiry point on the host's monotonic
    clock (``HostServices.monotonic``).

    Attributes
    ----------
    operation_id
        Identity of the running operation; request and result envelopes
        carry the same value.
    dataset_id
        Optional dataset correlation id, or ``None`` when the operation
        is not part of a dataset.
    deadline_monotonic
        Deadline on the host's monotonic clock in seconds. Once
        ``HostServices.monotonic()`` reaches it, the operation must fail
        rather than transmit.

    See Also
    --------
    Adapter : lifecycle that consumes a context per operation.
    HostServices : scoped services that own the monotonic clock.
    """

    operation_id: str
    dataset_id: str | None
    deadline_monotonic: float

    def is_cancelled(self) -> bool:
        """Report whether the host has cancelled the operation."""

    async def mark_dispatch_started(self) -> None:
        """Mark dispatch immediately before the adapter's first transmit.

        The host uses this marker to tell failures that never reached
        the device (``dispatch_state: "not_dispatched"``) from uncertain
        outcomes after a transmit (``dispatch_state: "unknown"``).
        """


class HostServices(Protocol):
    """Scoped host services: clocks, transport, and evidence recording.

    One services object is bound to an adapter session at ``open``.
    Adapters reach the device only through ``transfer`` and take time
    only from ``monotonic`` and ``utc_now``.

    See Also
    --------
    Adapter : receives these services at open.
    OperationContext : per-operation deadline and cancellation state.
    """

    def monotonic(self) -> float:
        """Return the current reading of the host's monotonic clock in seconds."""

    def utc_now(self) -> str:
        """Return the current UTC time as an ISO-8601 string."""

    async def transfer(
        self, transaction: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]:
        """Perform one bounded transport exchange with the device.

        Parameters
        ----------
        transaction
            Exchange description, for example ``{"kind":
            "stream_exchange", "data": b"ID?\\n", "max_bytes": 128,
            "termination": "lf"}``; the host enforces the declared
            bounds.
        context
            The operation context; a cancelled or expired operation
            fails instead of transmitting.

        Returns
        -------
        dict
            The raw device response, for example ``{"data": b"3.3\\n"}``.

        Raises
        ------
        TimeoutError
            If the operation is cancelled or past its deadline.
        ConnectionError
            If the transport has been lost.
        """

    async def close_transport(self, context: OperationContext) -> None:
        """Close the transport bound to this adapter session."""

    async def record_evidence(self, entry: dict[str, Any], context: OperationContext) -> None:
        """Append one evidence entry to the operation's evidence record."""


class CaptureServices(HostServices, Protocol):
    async def artifact_append(
        self, capture_id: str, data: bytes, context: OperationContext
    ) -> None: ...
    async def artifact_finalise(
        self, capture_id: str, metadata: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]: ...
    async def artifact_abort(self, capture_id: str) -> None: ...


class Adapter(Protocol):
    """Structural contract for a device plugin adapter.

    A plugin exposes a no-argument ``create_plugin()`` factory (named by
    the descriptor's ``integration.adapter.entry_point``) returning an
    adapter, which the host drives through a strict lifecycle: ``open``
    binds descriptor and services, ``execute`` runs one operation,
    ``next_event`` polls a subscription, and ``close`` releases the
    session. Construction and ``open`` stay free of device I/O; each
    session uses a fresh adapter instance.

    Examples
    --------
    A minimal read-only adapter skeleton:

    ```{.python}
    class DemoAdapter:
        async def open(self, descriptor, services, context): ...
        async def execute(self, request, context): ...
        async def next_event(self, subscription_id, context): ...
        async def close(self, context): ...
    ```

    See Also
    --------
    HostServices : scoped services handed over at open.
    OperationContext : identity, deadline, and cancellation per operation.
    """

    async def open(
        self, descriptor: dict[str, Any], services: HostServices, context: OperationContext
    ) -> None:
        """Bind the adapter to its descriptor and scoped host services.

        Called once per session before any other method. Implementations
        keep construction and ``open`` free of device I/O and defer all
        transport to the supplied ``services``.

        Parameters
        ----------
        descriptor
            The plugin's validated device descriptor.
        services
            Scoped host services for transport, clocks, and evidence.
        context
            Context for the open operation itself.
        """

    async def execute(
        self, request: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]:
        """Run one operation and return its result envelope.

        Implementations call ``context.mark_dispatch_started()``
        immediately before the first transmit, honour the context
        deadline and cancellation, never retry silently, and preserve
        uncertain outcomes: a failure after dispatch is reported with
        status ``"unknown"`` rather than ``"error"``.

        Parameters
        ----------
        request
            Operation envelope with exactly ``operation_id``, ``verb``
            and ``arguments``.
        context
            Identity, deadline, and cancellation state for the operation.

        Returns
        -------
        dict
            Result envelope: ``operation_id``, ``verb``, ``status``
            (``"ok"``, ``"error"`` or ``"unknown"``) and either ``data``
            or an ``error`` object carrying ``code``, ``message`` and
            ``dispatch_state``.
        """

    async def next_event(
        self, subscription_id: str, context: OperationContext
    ) -> dict[str, Any] | None:
        """Return the next pending event for a subscription, or None."""

    async def close(self, context: OperationContext) -> None:
        """Release the adapter session; tolerate repeated calls."""
