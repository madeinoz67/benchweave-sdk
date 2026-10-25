"""#556 Track B B3: the two dispositions the 0.5.0 schema publishes (the
README's normative section, rules 2 and 4; the maintainer's 2026-10-25
capacity-versus-declaration ruling).

A refusal is for a declaration conflict the schema cannot express;
a placement limit the declaration cannot see is a disclosure on the
REPORTED channel, never a refusal. The ``plot.over_slot`` self-reference
is the conflict (``classref_composed_plot_slot_mismatch``, the walk's);
a member ``plot`` on a page whose class template already hosts a plot is
the placement limit — the page keeps the class's plot, the member's plot
derives nothing, and every run REPORTS the row verbatim as the README
publishes it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import ResidualMember, derive_ui, find_reference

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

MEMBER_PIN = "member-plot.json"
VENDOR_URN = "com.meridian.m400.burst_mode/1.0.0"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _plot_member(
    *,
    page: str = "capture",
    over_slot: str = "burst",
) -> dict[str, Any]:
    return {
        "slot": "burst",
        "kind": "dataset",
        "claims": [VENDOR_URN],
        "page": page,
        "plot": {
            "kind": "time_series",
            "over_slot": over_slot,
            "series": "numeric_variables",
        },
    }


def _declaration(member: dict[str, Any]) -> dict[str, Any]:
    # MOVED DELIBERATELY 2026-10-26 (#556 B5): the declaration now carries
    # the vendor profile row the B4 admission rule requires — a rule B5
    # extended to the dataset kind with the target surface it guards, so a
    # row-less dataset member refuses where these arms derived green. The
    # arms' subject is the plot PLACEMENT disposition, which the row does
    # not touch.
    return {
        "contract_version": "0.1.0",
        "profiles": [
            {
                "id": "com.meridian.m400/1.0.0",
                "title": "Meridian M-400 composed profile",
                "channel_roles": ["digital_input"],
                "required_actions": [VENDOR_URN],
                "optional_actions": [],
            }
        ],
        "members": [member],
    }


def _descriptor(declaration: dict[str, Any]) -> dict[str, Any]:
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][VENDOR_URN] = {
        "binding": {"kind": "adapter", "key": "fixture"},
        "input_constraints": {"properties": {"burst_count": {"type": "integer"}}},
        "timeout_ms": 30000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:member-declaration:1.0.0",
            "path": MEMBER_PIN,
            "sha256": hashlib.sha256(_raw(declaration)).hexdigest(),
        }
    )
    return descriptor


def _derive_with(
    tmp_path: Path, declaration: dict[str, Any]
) -> Any:
    descriptor = _descriptor(declaration)
    scratch = tmp_path / "project"
    scratch.mkdir(parents=True)
    (scratch / MEMBER_PIN).write_bytes(_raw(declaration))
    (scratch / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    descriptor_path = scratch / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    return derive_ui(_raw(descriptor), REFERENCE, descriptor_path=descriptor_path)


def test_a_member_plot_on_a_page_hosting_a_class_plot_is_reported(
    tmp_path: Path,
) -> None:
    """The placement disposition (README rule 4): a dataset member's
    ``plot`` on a page whose class template already hosts a plot is
    ADMISSIBLE — it contradicts nothing the schema can see — so it never
    refuses. The page keeps the class's plot, the member's plot derives
    nothing, and the REPORTED row carries the README's exact text."""
    derived = _derive_with(tmp_path, _declaration(_plot_member()))
    rows = [
        row for row in derived.residual_members if row.kind == "composed plot"
    ]
    assert rows == [
        ResidualMember(
            "composed plot",
            "datasets and capture shapes",
            "burst",
            "page capture already hosts a plot (the page keeps the "
            "class's plot)",
        ),
    ], rows
    # MOVED DELIBERATELY 2026-10-26 (#556 B5, §4 V4 provenance): the
    # datasets ledger row gains the declared ``plot_kind`` — the member's
    # own choice, present exactly when the declaration carries one (the
    # derived plot row is wire-shaped by design, so the ledger is the
    # provenance surface for the vendor's choice).
    assert derived.composed_members["datasets"] == (
        {
            "slot": "burst",
            "action": VENDOR_URN,
            "page": "capture",
            "plot_kind": "time_series",
        },
    )


def test_a_member_plot_on_a_plotless_page_reports_no_row(tmp_path: Path) -> None:
    """MOVED DELIBERATELY 2026-10-26 (#556 B5, §4 V5): this arm pinned B3's
    interim state — a member ``plot`` on a page hosting no class template
    plot reported nothing, because deriving it was B5's to build. B5 builds
    it: on a page whose kind the manifest schema admits plots on (dataset,
    readings) the member's plot now DERIVES (the composing arms live in
    tests/test_classref_member_datasets.py), and on a configuration page —
    the page this arm names — no plot can render, so the placement limit
    discloses instead. The row family is unchanged: a placement limit the
    declaration cannot see is a disclosure, never a refusal."""
    derived = _derive_with(
        tmp_path, _declaration(_plot_member(page="configuration"))
    )
    assert [
        row for row in derived.residual_members if row.kind == "composed plot"
    ] == [
        ResidualMember(
            "composed plot",
            "datasets and capture shapes",
            "burst",
            "page configuration admits no plot (plots render on dataset "
            "and readings pages alone)",
        ),
    ], derived.residual_members


def test_plot_over_slot_mismatch_still_refuses_typed(tmp_path: Path) -> None:
    """The conflict disposition (README rule 2) rides the same member
    shape: ``plot.over_slot`` naming a slot other than the member's own
    refuses ``classref_composed_plot_slot_mismatch`` — the document
    refers to itself inconsistently, a declaration conflict, never a
    placement disclosure."""
    with pytest.raises(
        ValueError, match="^classref_composed_plot_slot_mismatch:"
    ):
        _derive_with(
            tmp_path, _declaration(_plot_member(over_slot="capture"))
        )
