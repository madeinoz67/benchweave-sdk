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
                "label": {"type": "string", "maxLength": 32},
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
