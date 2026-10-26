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
"""

from __future__ import annotations

from collections.abc import Mapping
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
