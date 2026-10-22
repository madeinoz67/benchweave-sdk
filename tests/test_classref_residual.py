"""Issue #541 slice 1: residual action resolution (design record
``.claude/deep-review/2026-10-22-issue541-classref-composition.md``).

Three-layer action resolution, actions arm. This file pins the split of the
seven former ``classref_unknown_action`` sites into integrity faults (still
refusing, each with its own code) and the recoverable knowledge gap (the
residual member derives, provenance-labelled, never silent).

Arms follow the record's acceptance metrics: M1 (the refusal is gone for the
recoverable case), M2 (nothing degrades silently), M3 (the layers are
distinguishable), M4 (the integrity refusals survive), M5 (RED-sanity — run
manually per the record; the neutralizations are ``cp``-backed, never
``git checkout``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref import (
    coverage_plan_without_reference,
    derive_ui,
    find_reference,
)

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")

#: A residual action: declared by the descriptor, described by no served
#: OTDP row and no pinned vendor catalog. Invented identity throughout.
GHOST_URN = "com.veridian-labs.ghost/1.0.0"


def _ghost_action(constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    """A descriptor action row for the residual fixture action."""
    return {
        "binding": {"kind": "adapter", "key": "ghost"},
        "input_constraints": constraints or {},
        "timeout_ms": 1000,
        "side_effect": "none",
        "cancellable": True,
        "retry": "never",
    }


def _acceptance_descriptor() -> dict[str, Any]:
    """The slice-1 acceptance descriptor: mostly a class (logic analyser),
    plus one action no served catalog describes (record §7 M1)."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                "label": {"type": "string"},
            },
            "required": ["holdoff_ms"],
        }
    )
    return descriptor


def _copy_project_files(destination: Path) -> Path:
    """The f1 descriptor plus its pinned files, copied so a test can tamper
    with the pinned bytes without touching the shared fixtures."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("descriptor-f1.json", "vendor-catalog.json", "vectors-f1.json"):
        (destination / name).write_bytes((FIXTURES / name).read_bytes())
    return destination


# ---------------------------------------------------------------------------
# M4 — the integrity refusals survive, each with its own code (record §7.4).
# The four former integrity sites of the ``classref_unknown_action`` split
# (record §1) keep refusing; only the code names change.
# ---------------------------------------------------------------------------


def test_m4_tampered_vendor_catalog_digest_refuses(tmp_path: Path) -> None:
    """A pinned vendor catalog whose bytes do not match its sha256 pin is an
    integrity fault (tampering or corruption) and refuses typed — never the
    old shared ``classref_unknown_action``."""
    project = _copy_project_files(tmp_path / "digest")
    catalog = json.loads((project / "vendor-catalog.json").read_bytes())
    catalog["actions"]["com.veridian-labs.ghost/1.0.0"] = {
        "input_schema": {"type": "object"},
        "side_effect": "none",
    }
    (project / "vendor-catalog.json").write_bytes(
        (json.dumps(catalog, indent=2) + "\n").encode()
    )
    # The pin still names the ORIGINAL digest: the bytes moved under it.
    with pytest.raises(
        ValueError, match="^classref_vendor_catalog_digest_mismatch:"
    ):
        derive_ui(
            (project / "descriptor-f1.json").read_bytes(), REFERENCE,
            descriptor_path=project / "descriptor-f1.json",
        )


def test_m4_unreadable_vendor_catalog_refuses(tmp_path: Path) -> None:
    """A pinned vendor catalog that cannot be read is a platform or project
    fault and refuses with its own code."""
    project = _copy_project_files(tmp_path / "unreadable")
    (project / "vendor-catalog.json").unlink()
    with pytest.raises(ValueError, match="^classref_vendor_catalog_unreadable:"):
        derive_ui(
            (project / "descriptor-f1.json").read_bytes(), REFERENCE,
            descriptor_path=project / "descriptor-f1.json",
        )


def test_m4_missing_profile_catalog_refuses() -> None:
    """A descriptor whose otdp_version has no served profile catalog row is
    a platform fault (incomplete installation) and refuses with its own
    code. The reference-less coverage seam is the public path that reaches
    the catalog resolution without a prior descriptor-schema refusal."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["otdp_version"] = "9.9.9"
    with pytest.raises(ValueError, match="^classref_profile_catalog_unserved:"):
        coverage_plan_without_reference(descriptor, FIXTURES / "descriptor-f1.json")


def test_m4_absent_profile_row_refuses() -> None:
    """A reference whose profile is absent from the served profile catalog
    is a platform fault and refuses with its own code."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["profiles"] = ["otdp.logic_analyser/9.9.9"]
    reference = {**REFERENCE, "profile_id": "otdp.logic_analyser/9.9.9"}
    with pytest.raises(ValueError, match="^classref_profile_absent:"):
        derive_ui(
            json.dumps(descriptor).encode(), reference,
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )


# ---------------------------------------------------------------------------
# M1 — the refusal is gone for the recoverable case (record §7.1).
# ---------------------------------------------------------------------------


def test_m1_residual_descriptor_derives_zero_refusals() -> None:
    """The acceptance descriptor (mostly a class, plus one action no catalog
    describes) derives with zero refusals, and 100% of the descriptor's
    declared actions appear in the control plan with a non-null resolution.
    The denominator is asserted from the descriptor, never a literal."""
    descriptor = _acceptance_descriptor()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    declared = set(descriptor["actions"])
    assert declared, "the acceptance descriptor declares actions"
    planned = set(derived.control_plan)
    assert planned == declared
    missing = declared - planned
    assert not missing, f"declared but unplanned: {sorted(missing)}"
    unresolved = sorted(
        urn for urn, row in derived.control_plan.items() if not row.get("resolution")
    )
    assert not unresolved, f"plan rows without resolution: {unresolved}"


def test_m1_residual_row_is_honest_about_its_constraints() -> None:
    """KILL (d) arm: the residual row's field rows match the descriptor's
    declared input_constraints — the generic surface admits exactly what the
    plugin declared, no more."""
    descriptor = _acceptance_descriptor()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    ghost = derived.control_plan[GHOST_URN]
    assert ghost["resolution"] == "custom"
    by_field = {row["field"]: row for row in ghost["fields"]}
    holdoff = by_field["holdoff_ms"]
    assert holdoff["mode"] == "numeric"
    assert holdoff["minimum"] == 0
    assert holdoff["maximum"] == 5000
    label = by_field["label"]
    assert label["mode"] == "text"
    # holdoff_ms is required and expressible: the action is L2 (staging).
    assert ghost["level"] == "L2"


# ---------------------------------------------------------------------------
# M3 — the layers are distinguishable (record §7.3). Slice-1 legs: the same
# URN derives "custom" with no catalog row and "catalog" when a served
# catalog describes it. (The "composed" leg is slice 2.)
# ---------------------------------------------------------------------------


def test_m3_same_urn_custom_without_catalog_row(tmp_path: Path) -> None:
    descriptor = _acceptance_descriptor()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=FIXTURES / "descriptor-f1.json",
    )
    assert derived.control_plan[GHOST_URN]["resolution"] == "custom"


def test_m3_same_urn_catalog_when_a_served_catalog_describes_it(
    tmp_path: Path,
) -> None:
    """The same URN, described by a pinned vendor catalog this time, derives
    resolution "catalog" — one URN, two distinct outcomes, the layer decided
    by what describes the action, never by the URN's spelling."""
    import hashlib

    project = _copy_project_files(tmp_path / "pinned")
    catalog = json.loads((project / "vendor-catalog.json").read_bytes())
    catalog["actions"][GHOST_URN] = {
        "description": "Pinned residual twin.",
        "input_schema": {
            "type": "object",
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                "label": {"type": "string"},
            },
            "required": ["holdoff_ms"],
        },
        "side_effect": "none",
    }
    raw_catalog = (json.dumps(catalog, indent=2) + "\n").encode()
    (project / "vendor-catalog.json").write_bytes(raw_catalog)
    descriptor = json.loads((project / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                "label": {"type": "string"},
            },
            "required": ["holdoff_ms"],
        }
    )
    for row in descriptor["contracts"]:
        if row["id"].startswith("urn:veridian:vendor-catalog"):
            row["sha256"] = hashlib.sha256(raw_catalog).hexdigest()
    derived = derive_ui(
        json.dumps(descriptor).encode(), REFERENCE,
        descriptor_path=project / "descriptor-f1.json",
    )
    assert derived.control_plan[GHOST_URN]["resolution"] == "catalog"


def test_m3_reference_less_plan_matches_derive_ui() -> None:
    """The same treatment on the reference-less path: coverage plans cannot
    disagree with derive_ui — the residual member derives, resolution
    "custom", where the old path refused."""
    descriptor = _acceptance_descriptor()
    plan, _actions = coverage_plan_without_reference(
        descriptor, FIXTURES / "descriptor-f1.json"
    )
    assert set(plan) == set(descriptor["actions"])
    assert plan[GHOST_URN]["resolution"] == "custom"


# ---------------------------------------------------------------------------
# The narrowing discipline survives in the no-catalogue-row mode: the closed
# keyword vocabulary and the empty-admittance refusal keep refusing (record
# §8 — unchanged for layer 3).
# ---------------------------------------------------------------------------


def test_residual_mode_refuses_outside_the_closed_vocabulary() -> None:
    """A residual constraint fragment using a keyword outside the closed
    intersection vocabulary refuses classref_constraint_unsupported — no
    catalogue row does not mean no vocabulary."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {"properties": {"label": {"type": "string", "format": "email"}}}
    )
    with pytest.raises(ValueError, match="^classref_constraint_unsupported:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )


def test_residual_mode_refuses_empty_admittance() -> None:
    """A residual required field whose declared bounds admit nothing refuses
    classref_effective_schema_empty — the generic surface never renders a
    control that admits no value (record §8, unchanged)."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][GHOST_URN] = _ghost_action(
        {
            "properties": {
                "holdoff_ms": {"type": "integer", "minimum": 10, "maximum": 5},
            },
            "required": ["holdoff_ms"],
        }
    )
    with pytest.raises(ValueError, match="^classref_effective_schema_empty:"):
        derive_ui(
            json.dumps(descriptor).encode(), REFERENCE,
            descriptor_path=FIXTURES / "descriptor-f1.json",
        )
