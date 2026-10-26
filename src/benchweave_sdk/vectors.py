"""The vectors.json evidence vocabulary (issue #566 row 11, golden vectors).

One pure validator shared by the two consumers that judge a plugin's
rehearsal script: the standalone host's script loader
(``benchweave_sdk_server.session.vectors_script``, which surfaces these
refusals as the typed ``not_ready`` connect mapping) and the scaffolded
plugin test suite (the anti-circularity invariant seeded into every
generated project). One mechanism, never a re-implementation on either
side — a host that disagrees with the plugin's own test would train
authors to ship what the gate accepts by luck.

The vocabulary: a file-level ``evidence`` key of ``"synthetic"`` (the
default when absent — an absent key claims nothing) or ``"hardware"``; a
row-level ``evidence`` key of the same two values; a row claiming
``"hardware"`` carries a ``recorded`` provenance object whose ``when`` is a
non-empty string. Refuses with ``standalone_vectors_evidence_unknown:`` and
``standalone_vectors_evidence_unrecorded:`` (STD-4), naming the row where a
row is at fault.

What this does NOT catch, on purpose: the validator proves that a hardware
CLAIM travels with recorded provenance, not that the provenance is true.
Hand-recorded bytes are the anti-circularity evidence precisely because no
builder produced them — that property belongs to the capture workflow, and
a forged ``recorded`` object passes here. The honest bound is the guide's
rule and the review's job, not this check's.

Understatement is not a refusal: a file labelled ``"synthetic"`` whose row
carries properly-recorded hardware bytes claims less than it holds. Only
overstatement — a hardware label over rows that carry no recorded bytes —
refuses.

The demand-order half (issue #567 row 12) lives here too:
:func:`validate_vectors_walk_order` rehearses the descriptor walk over the
corpus and refuses on order drift. The corpus alone cannot express which
row serves which parameter — that mapping is the plugin's protocol code —
so the rehearsal observes the adapter's own demands; a static order check
of the corpus bytes is undecidable, which is the named bound.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

#: The evidence vocabulary: ``synthetic`` (the default; builder-generated
#: rehearsal bytes) and ``hardware`` (hand-recorded bytes that no builder
#: produced — the anti-circularity slot).
EVIDENCE_LEVELS: tuple[str, ...] = ("synthetic", "hardware")


def _row_name(row: Mapping[str, Any], index: int) -> str:
    """The row's declared name, or its index — the loader's own convention."""
    name = row.get("name")
    return str(name) if isinstance(name, str) and name else str(index)


def _recorded_when_is_present(row: Mapping[str, Any]) -> bool:
    """A recorded provenance object with a non-empty ``when`` string.

    ``when`` is the capture moment — the one field a builder cannot supply
    truthfully, so it is the one the gate requires. Any other field
    (transport, operator, notes) is optional author provenance.
    """
    recorded = row.get("recorded")
    if not isinstance(recorded, Mapping):
        return False
    when = recorded.get("when")
    return isinstance(when, str) and bool(when.strip())


def validate_vectors_evidence(document: Mapping[str, Any], *, source: Path | str) -> None:
    """Refuse an evidence claim the vectors document cannot back.

    Parameters
    ----------
    document
        The parsed ``vectors.json`` object.
    source
        The document's location, embedded in refusals.

    Raises
    ------
    ValueError
        ``standalone_vectors_evidence_unknown:`` — a file-level or row-level
        evidence value outside :data:`EVIDENCE_LEVELS`; or
        ``standalone_vectors_evidence_unrecorded:`` — hardware claimed with
        no recorded exchange to back it (file level), or a row claiming
        hardware without a ``recorded`` provenance object carrying a
        non-empty ``when``.

    Examples
    --------
    >>> from benchweave_sdk.vectors import validate_vectors_evidence
    >>> validate_vectors_evidence(
    ...     {"evidence": "synthetic", "exchanges": []}, source="vectors.json")
    >>> validate_vectors_evidence(
    ...     {"evidence": "hardware", "exchanges": []}, source="vectors.json")
    Traceback (most recent call last):
        ...
    ValueError: standalone_vectors_evidence_unrecorded: hardware evidence is \
claimed but no exchange carries recorded bytes in vectors.json
    """
    level = document.get("evidence", "synthetic")
    if level not in EVIDENCE_LEVELS:
        raise ValueError(
            f"standalone_vectors_evidence_unknown: {level!r} (expected "
            f'"synthetic" or "hardware") at file level in {source}'
        )
    rows = document.get("exchanges", [])
    recorded_rows = 0
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, Mapping):
            # The loader's own row-shape refusal owns non-object rows; there
            # is no claim here to judge.
            continue
        row_level = row.get("evidence")
        if row_level is None:
            continue
        if row_level not in EVIDENCE_LEVELS:
            raise ValueError(
                f"standalone_vectors_evidence_unknown: row "
                f"{_row_name(row, index)}: {row_level!r} (expected "
                f'"synthetic" or "hardware") in {source}'
            )
        if row_level == "hardware":
            if not _recorded_when_is_present(row):
                raise ValueError(
                    f"standalone_vectors_evidence_unrecorded: row "
                    f"{_row_name(row, index)}: hand-recorded bytes need a "
                    f'"recorded" provenance object with a non-empty "when" '
                    f"in {source}"
                )
            recorded_rows += 1
    if level == "hardware" and recorded_rows == 0:
        raise ValueError(
            f"standalone_vectors_evidence_unrecorded: hardware evidence is "
            f"claimed but no exchange carries recorded bytes in {source}"
        )



# --- the demand-order half (issue #567 row 12) --------------------------------


class _WalkVerdict(Exception):
    """Internal: a named walk verdict (code + detail), re-raised as ValueError."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _WalkDouble:
    """A byte-level services double for one walk rehearsal.

    Sends match the corpus demand rows (rows carrying a request) in row
    order; the matched response is returned in the same transfer for the
    whole-dict dialect, or queued for the next receive in the split
    dialect. Receives serve the queued response, then unsolicited rows
    (response-only rows) in row order, then the quiet line. This is not
    the rehearsal mock: it matches demands on bytes only, so the mock's
    whole-dict exactness and RECEIVE-outcome semantics stay the
    rehearsal's domain.
    """

    def __init__(
        self,
        demands: list[tuple[int, bytes, bytes]],
        unsolicited: list[tuple[int, bytes]],
    ) -> None:
        self._demands = demands
        self._unsolicited = unsolicited
        self._queued: bytes | None = None

    def transfer(self, transaction: Mapping[str, Any], context: Any) -> dict[str, Any]:
        kind = transaction.get("kind")
        if kind in ("stream_receive", "can_receive"):
            if self._queued is not None:
                served, self._queued = self._queued, None
                return {"data": served}
            if self._unsolicited:
                _, response = self._unsolicited.pop(0)
                return {"data": response}
            return {"data": b""}
        data = transaction.get("data")
        if not isinstance(data, (bytes, bytearray)):
            raise _WalkVerdict("vectors_walk_order_unwalkable", f"transfer kind {kind!r}")
        if not self._demands:
            raise _WalkVerdict(
                "vectors_walk_order_exhausted", f"the corpus carries no row for {bytes(data)!r}"
            )
        row_index, request, response = self._demands.pop(0)
        if request != bytes(data):
            raise _WalkVerdict(
                "vectors_walk_order_mismatch",
                f"corpus row {row_index} requests {request!r}, "
                f"the adapter demands {bytes(data)!r}",
            )
        if kind == "stream_exchange":
            return {"data": response}
        self._queued = response
        return {}

    def leftover(self) -> list[int]:
        return [index for index, _, _ in self._demands] + [
            index for index, _ in self._unsolicited
        ]


def _decode_row_payload(text: Any, encoding: str) -> bytes:
    """One row payload to bytes under its encoding (the loader's grammar):
    non-string payloads coerce through ``str()`` (the default dialect's
    compat mode); ``hex`` takes ``bytes.fromhex``."""
    if not isinstance(text, str):
        return str(text).encode("ascii")
    if encoding == "ascii":
        return text.encode("ascii")
    return bytes.fromhex(text)


async def _run_walk(
    create_plugin: Callable[[], Any],
    descriptor: Mapping[str, Any],
    double: _WalkDouble,
) -> list[str]:
    """Drive identify, then each readable parameter in descriptor order.

    Returns the walk labels for verdict naming; a refusal encountered
    mid-step is re-raised with the step annotated.
    """
    from .testing import MockContext

    labels = ["identify"] + [
        str(row.get("name"))
        for row in descriptor.get("parameters", [])
        if isinstance(row, Mapping) and row.get("access") in ("ro", "rw")
    ]

    class _Services:
        async def transfer(
            self, transaction: Mapping[str, Any], context: Any
        ) -> dict[str, Any]:
            return double.transfer(transaction, context)

        def monotonic(self) -> float:
            return 0.0

        def utc_now(self) -> str:
            return "2026-01-01T00:00:00Z"

        async def record_evidence(self, entry: dict[str, Any], context: Any) -> None:
            return None

        async def close_transport(self, context: Any) -> None:
            return None

    plugin = create_plugin()
    context = MockContext("walk-1", deadline_monotonic=1.0)
    await plugin.open(descriptor, _Services(), context)
    try:
        for position, label in enumerate(labels):
            request = {
                "operation_id": "walk-1",
                "verb": "identify" if position == 0 else "read",
                "arguments": {} if position == 0 else {"parameter": label},
            }
            try:
                result = await plugin.execute(request, context)
            except _WalkVerdict as verdict:
                raise _WalkVerdict(
                    verdict.code,
                    f"at walk step {position} ({label}): {verdict.detail}",
                ) from None
            except Exception as exc:
                raise _WalkVerdict(
                    "vectors_walk_order_unwalkable",
                    f"at walk step {position} ({label}): {type(exc).__name__}: {exc}",
                ) from None
            if not isinstance(result, Mapping) or result.get("status") != "ok":
                error = result.get("error", {}) if isinstance(result, Mapping) else {}
                raise _WalkVerdict(
                    "vectors_walk_order_unwalkable",
                    f"at walk step {position} ({label}): the adapter refused: "
                    f"{error.get('code', result)}",
                )
    finally:
        await plugin.close(context)
    return labels


def validate_vectors_walk_order(
    create_plugin: Callable[[], Any],
    descriptor: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    source: Path | str,
) -> None:
    """Rehearse the descriptor walk over the corpus; refuse on order drift.

    The shipped driver walks the descriptor: identify, then each readable
    parameter in declaration order. A corpus ordered against some other
    walk rehearses a flow the host never runs (issue #567 row 12). This
    rehearsal drives the plugin's own adapter over a byte-matching double
    and refuses when the corpus demands and the walk demands disagree.

    Parameters
    ----------
    create_plugin
        The plugin's factory (``create_plugin``).
    descriptor
        The parsed descriptor; ``parameters[]`` declaration order defines
        the walk.
    document
        The parsed ``vectors.json``.
    source
        The corpus location, embedded in refusals.

    Raises
    ------
    ValueError
        ``vectors_walk_order_mismatch:`` — a demand differs from the next
        corpus demand row (naming the walk step, the corpus row and both
        byte strings); ``vectors_walk_order_exhausted:`` — the corpus
        carries no row for a walk demand;
        ``vectors_walk_order_unconsumed:`` — rows the walk never reaches;
        ``vectors_walk_order_unwalkable:`` — the adapter refuses the walk,
        raises, or needs a transfer kind the double cannot match. The
        last one is the named "cannot check" result: never a quiet pass.

    What this does NOT catch: a corpus whose demand order matches while
    its responses lie — response truth stays the mock's exact-match
    domain. And the static bound: the corpus alone cannot express which
    row serves which parameter (that mapping is plugin code), so no check
    of the corpus bytes alone can decide order; the rehearsal is what
    makes it decidable.
    """
    rows_doc = document.get("exchanges", [])
    demands: list[tuple[int, bytes, bytes]] = []
    unsolicited: list[tuple[int, bytes]] = []
    file_encoding = document.get("encoding", "ascii")
    for index, row in enumerate(rows_doc if isinstance(rows_doc, list) else []):
        if not isinstance(row, Mapping):
            continue
        encoding = row.get("encoding", file_encoding)
        if encoding not in ("ascii", "hex"):
            raise ValueError(
                f"standalone_vectors_encoding_unknown: row {_row_name(row, index)}: "
                f"{encoding!r} (expected \"ascii\" or \"hex\") in {source}"
            )
        response = _decode_row_payload(row["response"], encoding)
        if "request" in row:
            demands.append(
                (index, _decode_row_payload(row["request"], encoding), response)
            )
        else:
            unsolicited.append((index, response))
    double = _WalkDouble(demands, unsolicited)
    try:
        _run_walk_sync(create_plugin, descriptor, double)
    except _WalkVerdict as verdict:
        raise ValueError(f"{verdict.code}: {source}: {verdict.detail}") from None
    leftover = double.leftover()
    if leftover:
        names = ", ".join(
            f"row {index} ({_row_name(rows_doc[index], index)}: "
            f"{rows_doc[index].get('request', 'unsolicited')!r})"
            for index in leftover
            if index < len(rows_doc)
        )
        raise ValueError(
            f"vectors_walk_order_unconsumed: {source}: the walk the descriptor "
            f"defines never reaches {names}"
        )


def _run_walk_sync(
    create_plugin: Callable[[], Any],
    descriptor: Mapping[str, Any],
    double: _WalkDouble,
) -> None:
    """``_run_walk`` on the caller's event loop (tests and callers alike)."""
    import asyncio

    asyncio.run(_run_walk(create_plugin, descriptor, double))
