"""The rendered-output gate (gateway #463 L2, record §5/D5).

Renders the derived (or hand-authored) presentation through the standalone
host over an in-process ASGI client, censuses the served HTML on the
ui-contract §E.1 surfaces only, and asserts the numeric expectation
document, the forbid list, the always-on D14 coverage arm and the declared
deviation ledger. Findings are typed (``classref_gate_*``); a clean run
exits empty. A clean gate is never admission, approval to apply settings
or permission to operate hardware.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .classref import (
    LAYOUT_EXTENSION_KEY,
    derive_ui,
    find_reference,
)


@dataclass(frozen=True)
class GateFinding:
    code: str
    detail: str


@dataclass(frozen=True)
class GateReport:
    findings: tuple[GateFinding, ...]
    reported_deviations: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


#: The §E.1 field-element class hooks whose `id` is the host render's
#: ``action-<binding>-<field>`` control key — the per-action attribution the
#: L2 coverage arm reads (the wrapper ``bw-<kind>`` hook carries no id).
_STAGED_FIELD_CLASSES = frozenset(
    {
        "bw-numeric__field",
        "bw-text__field",
        "bw-select__field",
        "bw-boolean__control",
    }
)


class _CensusParser(HTMLParser):
    """Counts components by contract-pinned surfaces only (record §5/4)."""

    def __init__(self) -> None:
        super().__init__()
        self.lane_labels: list[str] = []
        self._label_depth = 0
        self.panels = 0
        self.buttons: list[str] = []
        self.numerics = 0
        self.texts = 0
        self.selects = 0
        self.booleans = 0
        self.mode_banners = 0
        self.lanes_figures = 0
        self.lane_kinds: dict[str, int] = {}
        self.confirms = 0
        self.data_tables = 0
        self.readings = 0
        self.plots = 0
        self._button_depth = 0
        # The rendered staging controls' own `id`s — one per input
        # element, carrying the host render's `action-<binding>-<field>`
        # key, so the coverage arm can attribute a control to its action.
        self.staged_control_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        data = dict(attrs)
        if _STAGED_FIELD_CLASSES.intersection(classes):
            control_id = data.get("id")
            if control_id:
                self.staged_control_ids.append(control_id)
        if "bw-panel" in classes:
            self.panels += 1
        if "bw-mode-banner" in classes:
            self.mode_banners += 1
        if "bw-lanes" in classes and tag == "figure":
            self.lanes_figures += 1
        if "bw-lanes__label" in classes:
            self.lane_labels.append("")
            self._label_depth += 1
        if tag == "div" and "bw-lanes__lane" in classes:
            kind = data.get("data-bw-lane-kind") or ""
            self.lane_kinds[kind] = self.lane_kinds.get(kind, 0) + 1
        if "bw-numeric" in classes:
            self.numerics += 1
        if "bw-text" in classes:
            self.texts += 1
        if "bw-select" in classes:
            self.selects += 1
        if "bw-boolean" in classes:
            self.booleans += 1
        if "bw-data-table" in classes:
            self.data_tables += 1
        if "bw-reading" in classes:
            self.readings += 1
        if "bw-plot" in classes:
            self.plots += 1
        if "bw-confirm" in classes:
            self.confirms = 1
        if "bw-button" in classes and tag == "button":
            self.buttons.append("")  # label captured in handle_data
            self._button_depth += 1

    def handle_data(self, payload: str) -> None:
        if self._button_depth:
            self.buttons[-1] += payload
        if self._label_depth and self.lane_labels:
            self.lane_labels[-1] += payload

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._button_depth:
            self._button_depth -= 1
        if tag == "span" and self._label_depth:
            self._label_depth -= 1


def census(html: str) -> dict[str, Any]:
    """One served page's component census on §E.1 surfaces."""
    parser = _CensusParser()
    parser.feed(html)
    return {
        "panels": parser.panels,
        "buttons": [label.strip() for label in parser.buttons],
        "numerics": parser.numerics,
        "text": parser.texts,
        "select": parser.selects,
        "boolean": parser.booleans,
        "mode_banners": parser.mode_banners,
        "lanes_figures": parser.lanes_figures,
        "lane_kinds": dict(parser.lane_kinds),
        "confirms": parser.confirms,
        "data_tables": parser.data_tables,
        "readings": parser.readings,
        "plots": parser.plots,
        "lane_labels": [
            label.strip().removesuffix(" hidden").strip()
            for label in parser.lane_labels
        ],
        "staged_control_ids": list(dict.fromkeys(parser.staged_control_ids)),
    }


def _derive_for_project(
    descriptor_raw: bytes, reference: dict[str, Any] | None, descriptor_path: Path
) -> Any:
    if reference is None:
        
        descriptor = json.loads(descriptor_raw)
        references = [
            found
            for profile in descriptor.get("profiles") or []
            if (found := find_reference(str(profile))) is not None
        ]
        if not references:
            return None
        reference = references[0]
    return derive_ui(descriptor_raw, reference, descriptor_path=descriptor_path)


def _page_ids(derived: Any) -> list[str]:
    return [str(page["id"]) for page in derived.manifest["pages"]]


def _not_d7(expectation_id: str) -> bool:
    """The D7 carve-out: an id naming the abort class never downgrades.

    The 2026-10-23 fold (B3) removed a ``protected`` parameter that was
    structurally unreachable here: this predicate sees §E.1 COMPONENT
    names (``button``, ``numeric-input``, …), which can never equal an
    action URN — the declared D7 widening is consumed by
    ``validate_declaration_vocabulary`` and the forbid arms, both of
    which DO see action URNs; this function's own abort-slug half is
    structural."""
    slug = str(expectation_id).split("/")[0].rsplit(".", 1)[-1]
    return slug != "abort"


def _assert_expect(
    expectation: dict[str, Any],
    censused: dict[str, dict[str, Any]],
    declared: frozenset[str] = frozenset(),
) -> tuple[list[GateFinding], list[str]]:
    """Census-vs-expect deltas, typed (record §5/5). M10/F7: an unknown
    component name and a per_page naming a non-served page both refuse —
    silence would launder the divergence. M8/F2: the attribute census is
    asserted with the count. F5-component (record §4's letter): a declared
    id downgrades exactly that expectation's failure to REPORTED, with
    the D7 carve-out untouched."""
    findings: list[GateFinding] = []
    reported: list[str] = []
    census_map = {
        "digital-lanes": "lanes_figures",
        "button": "buttons",
        "numeric-input": "numerics",
        "text-input": "text",
        "select": "select",
        "boolean-input": "boolean",
        "panel": "panels",
        "mode-banner": "mode_banners",
        "data-table": "data_tables",
        # The 0.3.0 widening: the readings/capture surfaces the corpus's
        # expect blocks name (§E.1 roots render_reading / render_plot).
        "reading-tile": "readings",
        "engineering-plot": "plots",
    }
    for name, row in expectation["components"].items():
        key = census_map.get(name)
        if key is None:
            raise ValueError(
                f"classref_gate_unknown_component: {name!r} keys no "
                "ui-contract §E.1 surface the census counts"
            )
        per_page = row.get("per_page")
        if per_page == "*":
            targets = {page: sc for page, sc in censused.items()}
        elif per_page is not None and per_page in censused:
            targets = {per_page: censused[per_page]}
        elif per_page is not None:
            raise ValueError(
                f"classref_gate_page: expectation per_page {per_page!r} names "
                "a page the render did not serve"
            )
        else:
            targets = None  # pooled across the render
        if targets is not None:
            for page, seen in targets.items():
                actual = seen.get(key) or 0
                if isinstance(actual, list):
                    actual = len(actual)
                if actual != row["count"]:
                    if name in declared and _not_d7(name):
                        reported.append(name)
                    else:
                        findings.append(
                            GateFinding(
                                "classref_gate_missing"
                                if isinstance(row["count"], int) and actual < row["count"]
                                else "classref_gate_excess",
                                f"{name} on {page}: expected {row['count']}, "
                                f"censused {actual}",
                            )
                        )
            seen_page = next(iter(targets.values())) if targets else {}
            lane_kinds = seen_page.get("lane_kinds", {})
            for selector, wanted in (row.get("attribute") or {}).items():
                kind = selector.removeprefix("data-bw-lane-kind=")
                seen_kind = lane_kinds.get(kind, 0)
                if seen_kind != wanted:
                    findings.append(
                        GateFinding(
                            "classref_gate_missing"
                            if seen_kind < wanted
                            else "classref_gate_excess",
                            f"{name} attribute {selector}: expected {wanted}, "
                            f"censused {seen_kind}",
                        )
                    )
        else:
            total = 0
            for seen in censused.values():
                value = seen.get(key)
                total += len(value) if isinstance(value, list) else (value or 0)
            if total != row["count"]:
                if name in declared and _not_d7(name):
                    reported.append(name)
                else:
                    findings.append(
                        GateFinding(
                            "classref_gate_missing"
                            if total < row["count"]
                            else "classref_gate_excess",
                            f"{name}: expected {row['count']} across the render, "
                            f"censused {total}",
                        )
                    )
    return findings, reported


#: The reference's forbid ids the gate implements (record §2.3/§5). The
#: confirm arm is the render census; the rest are document-level scans
#: over the served manifest — a schema-invalid manifest still gets the
#: TYPED gate finding before the host's load refuses it.
_FORBID_COLOR = "color-role-hint-on-lane"
_FORBID_TRACE = "untraceable-lane-label"
_FORBID_INTERMEDIATE = "intermediated-energy-removing-action"


def _forbid_findings(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    plan: dict[str, dict[str, Any]],
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    abort_slugs = {
        str(row.get("page"))  # placeholder replaced below
        for row in plan.values()
    }
    del abort_slugs
    # #541 slice 2 (record §6): the intermediated arm's protected set
    # widens by declaration — {abort-slug actions} ∪ {actions whose
    # composed class declares energy_removing}. The abort half stays the
    # structural slug guess; the declared half is the explicit evidence
    # the plan row carries.
    energy_slugs = {
        urn.split("/")[0].rsplit(".", 1)[-1]
        for urn, row in plan.items()
        if str(row.get("side_effect", "")) == "energy_removing"
    }
    for page in manifest.get("pages", []):
        for plot in page.get("plots", []):
            if plot.get("kind") != "digital_lanes":
                continue
            for hint in plot.get("channel_hints", []):
                if "color_role" in hint:
                    findings.append(
                        GateFinding(
                            "classref_gate_forbidden",
                            f"{_FORBID_COLOR}: {page.get('id')} plot hint "
                            f"{hint.get('variable_id')!r} carries "
                            f"color_role {hint.get('color_role')!r}",
                        )
                    )
    block = (manifest.get("extensions") or {}).get(LAYOUT_EXTENSION_KEY)
    for page in (block or {}).get("pages", []):
        for section in page.get("sections", []):
            for node in section.get("children", []):
                binding = str(node.get("binding_id", ""))
                if (
                    binding.split("/")[0].rsplit(".", 1)[-1] == "abort"
                    and node.get("kind") in ("numeric", "rotary", "button")
                    and node.get("kind") != "button"
                ):
                    findings.append(
                        GateFinding(
                            "classref_gate_forbidden",
                            f"{_FORBID_INTERMEDIATE}: abort binding carries a "
                            f"{node.get('kind')} control (record §C.1 "
                            "R-DEENERGISE-1: nothing between the operator "
                            "and de-energising)",
                        )
                    )
                elif (
                    binding in (_abort_action_slugs(descriptor) | energy_slugs)
                    and node.get("kind") in ("numeric", "rotary")
                ):
                    findings.append(
                        GateFinding(
                            "classref_gate_forbidden",
                            f"{_FORBID_INTERMEDIATE}: {binding} binding carries "
                            f"a {node.get('kind')} control (record §C.1 "
                            "R-DEENERGISE-1)",
                        )
                    )
    return findings


def _abort_action_slugs(descriptor: dict[str, Any]) -> set[str]:
    """The abort-class action slugs (the D7 set: energy-removing per the
    record §4 — the class example's abort action)."""
    return {
        str(urn).split("/")[0].rsplit(".", 1)[-1]
        for urn in descriptor.get("actions") or {}
        if str(urn).split("/")[0].rsplit(".", 1)[-1] == "abort"
    }


def _traceable_lane_labels(
    descriptor: dict[str, Any], descriptor_path: Path | None = None
) -> set[str]:
    """Descriptor channel ids + labels, the pinned decoder ids AND their
    document names (the same source the decoder-lane derivation uses),
    and the group pattern instantiations — everything a lane label may
    trace to (F4c)."""
    traceable: set[str] = set()
    for row in descriptor.get("channels") or []:
        traceable.add(str(row.get("id", "")))
        traceable.add(str(row.get("label", "")))
    for pin in descriptor.get("decoders") or []:
        traceable.add(str(pin.get("id", "")))
        if descriptor_path is None:
            continue
        try:
            from .presentation import read_file

            doc = json.loads(
                read_file(descriptor_path.parent / str(pin.get("path", "")))
            )
            traceable.add(str(doc.get("name", "")))
            traceable.add(str(doc.get("longname", "")))
        except (ValueError, OSError, json.JSONDecodeError):
            traceable.add(str(pin.get("id", "")))
    return traceable


def _lane_label_findings(
    labels: list[str],
    descriptor: dict[str, Any],
    descriptor_path: Path | None = None,
) -> list[GateFinding]:
    traceable = _traceable_lane_labels(descriptor, descriptor_path)
    findings: list[GateFinding] = []
    for label in labels:
        if label in traceable:
            continue
        if re.fullmatch(r"D\d+-D\d+", label):
            continue
        findings.append(
            GateFinding(
                "classref_gate_forbidden",
                f"{_FORBID_TRACE}: lane label {label!r} traces to no "
                "descriptor channel and no group pattern",
            )
        )
    return findings


def _coverage_findings(
    plan: dict[str, dict[str, Any]],
    censused: dict[str, dict[str, Any]],
    declaration: dict[str, Any],
    custom_minted: frozenset[str] = frozenset(),
) -> tuple[list[GateFinding], list[str]]:
    """The always-on D14 coverage arm (record §5.1): per action, a rendered
    control at its ladder level OR a declared deviation. Declared
    divergences ride back as REPORTED rows; undeclared ones fail.

    A residual member (resolution "custom", #541) is a disclosure, not a
    coverage question: it REPORTS labelled "custom" every run and cannot
    fail the gate for being custom. The #541 W6 fold sharpens that: the
    label says WHAT rendered — "custom, renders nothing" names the member
    whose controls are absent — and the divergence and coverage checks
    still run for custom rows (custom exempts a member from needing a
    catalogue, never from conformance). An uncovered custom member fails
    exactly when the DERIVATION minted control nodes for THAT action
    (``custom_minted``, per action — the G1/G2 fold of 2026-10-22: the
    discriminator used to be per page and read the SERVED manifest's
    section ids, so an L0 sibling on a page that mints a custom section
    reded for rendering nothing by design, an overlay that dropped the
    section bought a clean gate, and an authored section merely carrying
    the `-custom` id created a debt); an authored page that stands as
    authored (record §11 risk 4) or an L0 row with nothing derivable
    renders nothing BY DESIGN and stays a disclosure — no red, and no
    deviation needed.

    The L2 test is PER ACTION (RC fold, gateway #463): an L2 action is
    covered when ITS OWN inputs render — the host render's
    ``action-<binding>-<field>`` control ids for that action's derived field
    rows — never by the page's summed input count, which lets one L2
    action's controls cover a stripped sibling on the same page. The L1
    test stays its own button; the L3/L4 tests stay the plan-named page
    surface (data-table / lanes figure), counted per page, not per action."""
    findings: list[GateFinding] = []
    reported: list[str] = []
    declared_ids = {
        str(row.get("expectation_id")) for row in declaration.get("deviations", [])
    }
    for urn, row in sorted(plan.items()):
        slug = urn.split("/")[0].rsplit(".", 1)[-1]
        page = str(row["page"])
        seen = censused.get(page, {})
        buttons = seen.get("buttons", [])
        level = row["level"]
        covered = False
        if level == "L1" and slug in buttons:
            covered = True
        elif level == "L2" and slug in buttons:
            staged = set(seen.get("staged_control_ids", ()))
            covered = any(
                f"action-{slug}-{field_row.get('field')}" in staged
                for field_row in row.get("fields", ())
            )
        elif level == "L3":
            # L11: the plan's NAMED class — the settings data-table the
            # L3 layout derives — never any button that happens to render.
            covered = seen.get("data_tables", 0) >= 1
        elif level == "L4":
            # The dataset surface: a lanes figure OR the engineering plot
            # the widened plot kinds render (the 0.3.0 vocabulary — a
            # waveform/time_series dataset's coverage is its plot, never
            # a lanes figure it does not render).
            covered = (
                seen.get("lanes_figures", 0) >= 1 or seen.get("plots", 0) >= 1
            )
        is_custom = str(row.get("resolution", "catalog")) == "custom"
        if is_custom:
            # #541 record §4.3 + W6 fold: the disclosure lands in the
            # REPORTED channel EVERY run, ahead of any authored-ledger row
            # for the same urn (the label is the point: a bare id would
            # not say what the member is), and the checks below still
            # apply to the member.
            reported.append(
                f"custom: {urn}" if covered
                else f"custom, renders nothing: {urn}"
            )
        divergence = bool(row.get("divergence"))
        # A6's mechanism: the AUTHOR's ledger downgrades — the expander's
        # auto-deviation marks are informational only, or an emptied
        # ledger would launder the divergence. A declaration is itself
        # part of the report (A1/A10: the birth deviation REPORTS whether
        # or not the surface renders).
        if urn in declared_ids:
            reported.append(urn)
            continue
        if divergence:
            # An undeclared intended-vs-derived divergence FAILS whether
            # or not a control happens to render (record §3.9) — for a
            # custom member exactly as for a catalogued one.
            findings.append(
                GateFinding(
                    "classref_gate_undeclared",
                    f"{urn}: {row.get('divergence')}",
                )
            )
            continue
        if not covered:
            if is_custom and slug not in custom_minted:
                # Nothing was owed: the derivation minted no control node
                # for THIS action (an authored page standing as authored,
                # or an L0 row with nothing derivable) — the REPORTED
                # label above is the honest state, not a failure.
                continue
            findings.append(
                GateFinding("classref_gate_uncovered", f"{urn} renders no control at {level}")
            )
    return findings, reported


def _custom_minted_slugs(layout_block: dict[str, Any] | None) -> frozenset[str]:
    """The actions the DERIVATION minted control nodes for — every node
    binding id the derived layout block carries (#541 W6 fold, corrected
    by the G1/G2 fold of 2026-10-22). The discriminator is per ACTION and
    reads the derivation's own output, which the gate already holds: the
    served manifest's section ids answer a different question — what the
    overlay chose to serve. An overlay that drops the custom section must
    not clear the debt the derivation minted, and an authored section
    merely carrying the `-custom` id must not create one."""
    if not isinstance(layout_block, dict):
        return frozenset()
    return frozenset(
        str(node.get("binding_id"))
        for page in layout_block.get("pages", [])
        for section in page.get("sections", [])
        for node in section.get("children", [])
        if isinstance(node, dict) and node.get("binding_id") is not None
    )


def _custom_inventory_findings(
    ledger_custom: list[Any], derived_custom: set[str]
) -> list[str]:
    """The declaration's custom inventory, read back (#541 W10 fold): the
    authored ledger's ``custom_actions`` is compared against the derived
    custom set of the control plan, both directions, and every mismatch
    lands in the REPORTED channel — the inventory was write-only before
    (an authored ledger could omit every uncatalogued member, and a
    forged row naming a nonexistent URN passed). A mismatch is a
    disclosure divergence, REPORTED rather than refused: no schema
    governs this key set yet (deferral D8 records the standards motion)."""
    reported: list[str] = []
    ledger_actions: set[str] = set()
    for row in ledger_custom:
        action = row.get("action") if isinstance(row, dict) else None
        if action is None:
            reported.append(
                f"custom mismatch: malformed custom_actions row {row!r}"
            )
            continue
        ledger_actions.add(str(action))
    for urn in sorted(derived_custom - ledger_actions):
        reported.append(
            f"custom mismatch: {urn} derives residual but the authored "
            "declaration's custom_actions omits it"
        )
    for urn in sorted(ledger_actions - derived_custom):
        reported.append(
            f"custom mismatch: the authored declaration's custom_actions "
            f"names {urn}, which derives no residual member"
        )
    return reported


def _composed_inventory_findings(
    ledger_composed: list[Any],
    ledger_classes: list[Any],
    derived_composed: dict[str, str],
) -> list[str]:
    """The declaration's composed inventory, read back (the B6 fold of
    2026-10-23, mirroring ``_custom_inventory_findings`` after the design
    record §8's refute correction; R6 of the 2026-10-23 fold wave 3):
    the authored ledger's ``composed_actions`` and ``composed_classes``
    compare against the derived composed inventory, both directions,
    AND the comparison carries the action -> class MAPPING — the B6 cut
    compared two independent sets, so a ledger whose ``composed_actions``
    row named the WRONG class for an action (internally inconsistent
    with its own ``composed_classes``) verified clean and migrated with
    "nothing to do". Every mismatch lands in the REPORTED channel.
    ``derived_composed`` maps each derived composed action URN to its
    class URN; the class comparison runs over the class URNs those
    values carry — the APPLIED classes (R1), so a ledger naming a
    pin-declared class that applied nowhere is a mismatch naming what
    the class composes, never a false "no pin declares it". REPORTED,
    never a ``findings`` failure — the same no-schema-yet posture as the
    custom read-back (deferral D8)."""
    reported: list[str] = []
    ledger_actions: set[str] = set()
    ledger_composed_of: dict[str, str] = {}
    for row in ledger_composed:
        action = row.get("action") if isinstance(row, dict) else None
        if action is None:
            reported.append(
                f"composed mismatch: malformed composed_actions row {row!r}"
            )
            continue
        class_urn = row.get("class")
        if isinstance(class_urn, str):
            ledger_composed_of[str(action)] = class_urn
        ledger_actions.add(str(action))
    ledger_class_urns: set[str] = set()
    for row in ledger_classes:
        class_urn = row.get("class") if isinstance(row, dict) else None
        if class_urn is None:
            reported.append(
                f"composed mismatch: malformed composed_classes row {row!r}"
            )
            continue
        ledger_class_urns.add(str(class_urn))
    derived_class_urns = {
        class_urn for class_urn in derived_composed.values() if class_urn
    }
    for urn in sorted(set(derived_composed) - ledger_actions):
        reported.append(
            f"composed mismatch: {urn} derives composed but the authored "
            "declaration's composed_actions omits it"
        )
    for urn in sorted(ledger_actions - set(derived_composed)):
        reported.append(
            f"composed mismatch: the authored declaration's "
            f"composed_actions names {urn}, which derives no composed member"
        )
    # R6: the mapping comparison — a ledger row naming a class the action
    # does not derive composed of is a mismatch even when both sets agree.
    for action, wrong in sorted(ledger_composed_of.items()):
        derives = derived_composed.get(action)
        if derives is not None and wrong != derives:
            reported.append(
                f"composed mismatch: {action} derives composed of class "
                f"{derives} but the authored declaration's composed_actions "
                f"names {wrong}"
            )
    for class_urn in sorted(derived_class_urns - ledger_class_urns):
        reported.append(
            f"composed mismatch: class {class_urn} is composed here but "
            "the authored declaration's composed_classes omits it"
        )
    for class_urn in sorted(ledger_class_urns - derived_class_urns):
        reported.append(
            f"composed mismatch: the authored declaration's "
            f"composed_classes names {class_urn}, which composes no "
            "action this descriptor declares"
        )
    return reported


def verify_ui(
    project: Path,
    *,
    reference: dict[str, Any] | None = None,
    client: Any = None,
) -> GateReport:
    """The full gate: validate, derive, render, census, assert (record §5)."""
    package_root = project / "src"
    package_dir = next(
        (path for path in package_root.iterdir() if path.is_dir()), None
    )
    if package_dir is None:
        raise ValueError(f"classref_gate_project: no package under {package_root}")
    descriptor_path = package_dir / "descriptor.json"
    descriptor_raw = descriptor_path.read_bytes()
    derived = _derive_for_project(descriptor_raw, reference, descriptor_path)
    if derived is None:
        # The always-on arm alone (record §5.1): no class reference, no
        # expect assertions and no invented obligations — every declared
        # action still owes a rendered control or a declared deviation.
        
        from .classref import (
            coverage_plan_without_reference,
            declared_energy_removing,
            validate_declaration_vocabulary,
        )
        from .classref_gate_render import render_pages

        descriptor = json.loads(descriptor_raw)
        plan, _actions_map, ignored_pins, unapplied, empty_pins = (
            coverage_plan_without_reference(descriptor, descriptor_path)
        )
        manifest = json.loads((package_dir / "ui" / "manifest.json").read_bytes())
        pages = [str(page["id"]) for page in manifest.get("pages", [])]
        first = pages[0] if pages else ""
        plan = {urn: {**row, "page": row["page"] if row["page"] != "device-features" else first}
                for urn, row in plan.items()}
        rendered = render_pages(project, pages)
        censused = {page: census(html) for page, html in rendered.items()}
        declaration_path = package_dir / "ui" / "class-reference.json"
        declaration = (
            json.loads(declaration_path.read_bytes())
            if declaration_path.is_file()
            else {"deviations": []}
        )
        validate_declaration_vocabulary(
            set(plan), declaration,
            energy_removing=declared_energy_removing(plan),
        )
        coverage, reported = _coverage_findings(
            # The reference-less plan mints no layout (D2: no derive path
            # exists to mint one), so no custom member owes rendered
            # controls here — the derivation produced nothing, and the
            # per-action discriminator says exactly that.
            plan, censused, declaration, frozenset()
        )
        # W10: the read-back runs in this arm too — both arms read the
        # same authored declaration file. G5 (2026-10-22 fold): a project
        # with no class reference has no declaration to read back — no
        # tool writes ui/class-reference.json on this path (D2) — so the
        # honest report says the inventory is UNAVAILABLE, never a
        # mismatch blaming a declaration that does not exist.
        custom_urms = {
            urn
            for urn, row in plan.items()
            if str(row.get("resolution", "catalog")) == "custom"
        }
        composed_urms = {
            urn
            for urn, row in plan.items()
            if str(row.get("resolution", "catalog")) == "composed"
        }
        if declaration_path.is_file():
            reported.extend(
                _custom_inventory_findings(
                    declaration.get("custom_actions") or [], custom_urms
                )
            )
            # B6: the composed read-back runs in this arm too — both arms
            # read the same authored declaration file.
            reported.extend(
                _composed_inventory_findings(
                    declaration.get("composed_actions") or [],
                    declaration.get("composed_classes") or [],
                    {
                        urn: str(row.get("class", ""))
                        for urn, row in plan.items()
                        if str(row.get("resolution", "catalog")) == "composed"
                    },
                )
            )
        else:
            if custom_urms:
                reported.append(
                    f"custom inventory unavailable: {len(custom_urms)} residual "
                    "member(s) derive but no ui/class-reference.json exists "
                    "(no class reference matched; derive-ui writes the "
                    "declaration only with one)"
                )
            # R3 (2026-10-23 fold, wave 3): the composed half gets the same
            # explicit unavailable disclosure — it reported nothing, so a
            # composed member was invisible in this arm's REPORTED channel
            # on the natural reference-less state (D2).
            if composed_urms:
                reported.append(
                    f"composed inventory unavailable: {len(composed_urms)} "
                    "composed member(s) derive but no ui/class-reference.json "
                    "exists (no class reference matched; derive-ui writes the "
                    "declaration only with one)"
                )
        # B7: ignored pins disclose here too — the reference-less arm
        # resolves the same pinned documents.
        reported.extend(
            f"pinned document {path} contributed nothing"
            for path in ignored_pins
        )
        # R1/R5 (2026-10-23 fold, wave 3): the pin disclosures the
        # reference-carrying arm reports, on the same channel — a
        # pin-declared class that applied nowhere, and a vendor-catalog
        # pin that declared no actions.
        reported.extend(
            f"composed class {urn} is pinned ({pin_path}) but its claims "
            "name no action this descriptor declares"
            for urn, pin_path in unapplied
        )
        reported.extend(
            f"pinned document {path} contributed nothing (its vendor-catalog "
            "actions map is empty)"
            for path in empty_pins
        )
        return GateReport(findings=tuple(coverage), reported_deviations=tuple(reported))
    # The AUTHOR's ledger is the deviation record (A6's mechanism): when
    # the project carries ui/class-reference.json the gate reads THAT,
    # validated, in this arm too — the birth declaration is only the
    # fallback. H3: validation runs in both arms.
    from .classref import declared_energy_removing, validate_declaration_vocabulary

    authored_path = package_dir / "ui" / "class-reference.json"
    ledger = (
        json.loads(authored_path.read_bytes())
        if authored_path.is_file()
        else derived.declaration
    )
    vocabulary = set(derived.expectation.get("components", {}))
    vocabulary.update(derived.control_plan)
    protected = declared_energy_removing(derived.control_plan)
    validate_declaration_vocabulary(
        vocabulary, ledger, energy_removing=protected
    )
    ledger_ids = {
        str(row.get("expectation_id")) for row in ledger.get("deviations", [])
    }
    # H2: the manifest's layout block — authored via the overlay or derived
    # — is validated against the family schema; the canonical validator is
    # extension-blind, so this refusal is the block's only authority.
    from jsonschema import Draft202012Validator

    from .classref import layout_schema

    manifest = json.loads((package_dir / "ui" / "manifest.json").read_bytes())
    block = (manifest.get("extensions") or {}).get(LAYOUT_EXTENSION_KEY)
    if block is not None:
        layout_findings = list(
            Draft202012Validator(layout_schema()).iter_errors(block)
        )
        if layout_findings:
            raise ValueError(
                f"classref_layout_invalid: {layout_findings[0].message}"
            )
    from .classref_gate_render import render_pages

    descriptor = json.loads(descriptor_raw)
    # F4: the forbid arms run on the COMPOSED manifest before the render —
    # a schema-invalid manifest still gets the TYPED gate finding, never
    # only the host's load refusal.
    forbid_findings = _forbid_findings(manifest, descriptor, derived.control_plan)
    if forbid_findings:
        raise ValueError(f"{forbid_findings[0].code}: {forbid_findings[0].detail}")
    # F7: census the UNION — every derived page (the A4 baseline's
    # missing pages still render and census) plus every overlay-appended
    # page the served manifest declares, never silent on the extra set.
    pages = list(dict.fromkeys(
        _page_ids(derived)
        + [str(row.get("id")) for row in manifest.get("pages", [])]
    ))
    rendered = render_pages(project, pages)
    censused = {page: census(html) for page, html in rendered.items()}
    component_findings, component_reported = _assert_expect(
        derived.expectation, censused, frozenset(ledger_ids),
    )
    findings = list(component_findings)
    findings.extend(forbid_findings)
    # F4: every rendered lane label must trace to the descriptor's channel
    # identity or the group pattern.
    for seen in censused.values():
        findings.extend(
            _lane_label_findings(
                seen.get("lane_labels", []), descriptor, descriptor_path
            )
        )
    # A11's DOM-order arm made real: each layout page's button sequence
    # (the block's declaration order) appears in the censused page's
    # buttons in the same order — containment plus order, not counts.
    for layout_page in (block or {}).get("pages", []):
        declared = [
            str(node.get("binding_id"))
            for section in layout_page.get("sections", [])
            for node in section.get("children", [])
            if node.get("kind") == "button"
        ]
        page_id = str(layout_page.get("page_id"))
        seen_buttons = censused.get(page_id, {}).get("buttons", [])
        cursor = 0
        for binding_id in declared:
            while cursor < len(seen_buttons) and seen_buttons[cursor] != binding_id:
                cursor += 1
            if cursor >= len(seen_buttons):
                findings.append(
                    GateFinding(
                        "classref_gate_missing",
                        f"layout order on {page_id}: {binding_id!r} button out of "
                        f"declared position (censused {seen_buttons})",
                    )
                )
                break
            cursor += 1
    coverage, reported = _coverage_findings(
        derived.control_plan, censused, ledger,
        # G1/G2 fold: the RED criterion is the derivation's own layout
        # block — the statement of what should have rendered — never the
        # served manifest the overlay edits.
        _custom_minted_slugs(derived.layout_block),
    )
    reported.extend(component_reported)
    # W10: the authored ledger's custom inventory is read back against
    # the derived custom set — a mismatch is REPORTED, never silent (the
    # birth declaration compares equal by construction, so only an
    # authored edit moves these rows).
    reported.extend(
        _custom_inventory_findings(
            ledger.get("custom_actions") or [],
            {
                urn
                for urn, row in derived.control_plan.items()
                if str(row.get("resolution", "catalog")) == "custom"
            },
        )
    )
    # B6 (2026-10-23 fold): the composed inventory is read back beside
    # the custom one — the authored ledger's composed rows compare against
    # the derived composed sets, both directions, REPORTED and never a
    # findings failure (slice 1 learned this about custom_actions; the
    # design record §8's refute correction makes it mandatory here too).
    reported.extend(
        _composed_inventory_findings(
            ledger.get("composed_actions") or [],
            ledger.get("composed_classes") or [],
            {
                urn: str(row.get("class", ""))
                for urn, row in derived.control_plan.items()
                if str(row.get("resolution", "catalog")) == "composed"
            },
        )
    )
    # B7: pins whose documents matched neither shape discriminator are
    # disclosed on the REPORTED channel every run — never silent, never
    # a failure.
    reported.extend(
        f"pinned document {path} contributed nothing"
        for path in derived.ignored_pins
    )
    # R1/R5 (2026-10-23 fold, wave 3): the same channel carries a
    # pin-declared class that applied nowhere (its claims name no action
    # this descriptor declares) and a vendor-catalog pin that declared no
    # actions — disclosed every run, never drift and never a failure.
    reported.extend(
        f"composed class {urn} is pinned ({pin_path}) but its claims "
        "name no action this descriptor declares"
        for urn, pin_path in derived.unapplied_classes
    )
    reported.extend(
        f"pinned document {path} contributed nothing (its vendor-catalog "
        "actions map is empty)"
        for path in derived.empty_action_pins
    )
    findings.extend(coverage)
    forbidden = [
        GateFinding("classref_gate_forbidden", f"bw-confirm rendered on {page}")
        for page, seen in censused.items()
        if seen.get("confirms")
    ]
    findings.extend(forbidden)
    return GateReport(findings=tuple(findings), reported_deviations=tuple(reported))
