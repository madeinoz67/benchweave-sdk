# author: Stephen Eaton
"""Issue #567 row 12: the mock's demand-order contract.

A vectors corpus can be ordered against a walk the shipped driver never
performs — the plugin's own tests walk the corpus order and pass, while
the host session (identify, then each readable parameter in descriptor
order) wedges on the mock or proves a flow it never runs. The close is a
validation that works on what the corpus ALREADY carries plus the
adapter's own demand stream: the walk rehearsal. The corpus alone cannot
express which row serves which parameter (that mapping lives in the
plugin's protocol code), so a static check of the corpus bytes is
undecidable — the named bound. What the rehearsal does not catch: a
corpus whose demand order matches but whose responses lie; response
truth stays the mock's exact-match domain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.vectors import validate_vectors_walk_order

SOURCE = Path("vectors.json")


def _document(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"evidence": "synthetic", "exchanges": list(rows)}


class _ToyAdapter:
    """A two-parameter toy device: identify answers b"ID?", each read
    demands b"Q:" + the parameter name. One transfer per demand —
    whole-dict shape (the scaffold starter's dialect)."""

    def __init__(self) -> None:
        self.services = None

    async def open(self, descriptor: Any, services: Any, context: Any) -> None:
        self.services = services

    async def execute(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
        verb = request.get("verb")
        await context.mark_dispatch_started()
        if verb == "identify":
            raw = await self.services.transfer(
                {"kind": "stream_exchange", "data": b"ID?", "max_bytes": 64,
                 "termination": "lf", "exact_bytes": None},
                context,
            )
            return {"status": "ok", "data": {"manufacturer": raw["data"].decode()}}
        if verb == "read":
            name = request["arguments"]["parameter"]
            raw = await self.services.transfer(
                {"kind": "stream_exchange", "data": b"Q:" + name.encode(),
                 "max_bytes": 64, "termination": "lf", "exact_bytes": None},
                context,
            )
            return {"status": "ok", "data": {"parameter": name, "value": raw["data"].decode()}}
        return {"status": "error", "error": {"code": "UNSUPPORTED"}}

    async def next_event(self, subscription_id: Any, context: Any) -> None:
        return None

    async def close(self, context: Any) -> None:
        self.services = None


def _create_plugin() -> _ToyAdapter:
    return _ToyAdapter()


def _descriptor() -> dict[str, Any]:
    # Walk order is declaration order: beta first, then alpha.
    return {
        "parameters": [
            {"name": "beta", "type": "float", "access": "ro"},
            {"name": "alpha", "type": "float", "access": "ro"},
        ]
    }


def _row(request: bytes, response: bytes) -> dict[str, Any]:
    return {"request": request.decode(), "response": response.decode()}


def test_walk_order_matching_the_corpus_passes() -> None:
    document = _document(
        _row(b"ID?", b"TOY"),
        _row(b"Q:beta", b"1"),
        _row(b"Q:alpha", b"2"),
    )
    validate_vectors_walk_order(_create_plugin, _descriptor(), document, source=SOURCE)


def test_corpus_ordered_against_the_walk_refuses_naming_the_row() -> None:
    """The hazard: rows captured for alpha-then-beta while the shipped
    walk demands beta-then-alpha. Every plugin test that walks the corpus
    order passes; this refuses."""
    document = _document(
        _row(b"ID?", b"TOY"),
        _row(b"Q:alpha", b"2"),
        _row(b"Q:beta", b"1"),
    )
    with pytest.raises(ValueError, match="vectors_walk_order_mismatch:") as caught:
        validate_vectors_walk_order(_create_plugin, _descriptor(), document, source=SOURCE)
    message = str(caught.value)
    assert "beta" in message  # the walk position whose demand landed wrong
    assert "Q:beta" in message and "Q:alpha" in message


def test_corpus_shorter_than_the_walk_refuses_naming_the_position() -> None:
    document = _document(
        _row(b"ID?", b"TOY"),
        _row(b"Q:beta", b"1"),
    )
    with pytest.raises(ValueError, match="vectors_walk_order_exhausted:") as caught:
        validate_vectors_walk_order(_create_plugin, _descriptor(), document, source=SOURCE)
    assert "alpha" in str(caught.value)


def test_corpus_the_walk_never_reaches_refuses_naming_the_rows() -> None:
    """Rows ordered against a walk the shipped driver never performs are
    named, not silently served or silently ignored."""
    document = _document(
        _row(b"ID?", b"TOY"),
        _row(b"Q:beta", b"1"),
        _row(b"Q:alpha", b"2"),
        _row(b"Q:gamma", b"3"),
    )
    with pytest.raises(ValueError, match="vectors_walk_order_unconsumed:") as caught:
        validate_vectors_walk_order(_create_plugin, _descriptor(), document, source=SOURCE)
    assert "Q:gamma" in str(caught.value)


def test_the_bound_is_named_when_the_adapter_cannot_walk() -> None:
    """The named result the team lead requires in place of silence: when
    the walk cannot be rehearsed at all, the refusal says so and names
    why — never a quiet pass."""

    class _Broken(_ToyAdapter):
        async def execute(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
            return {"status": "error", "error": {"code": "UNSUPPORTED", "message": "no"}}

    document = _document(_row(b"ID?", b"TOY"))
    with pytest.raises(ValueError, match="vectors_walk_order_unwalkable:") as caught:
        validate_vectors_walk_order(_Broken, _descriptor(), document, source=SOURCE)
    assert "UNSUPPORTED" in str(caught.value)
