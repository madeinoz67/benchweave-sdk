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

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .classref import (
    derive_ui,
    find_reference,
    validate_declaration,
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


class _CensusParser(HTMLParser):
    """Counts components by contract-pinned surfaces only (record §5/4)."""

    def __init__(self) -> None:
        super().__init__()
        self.panels = 0
        self.buttons: list[str] = []
        self.numerics = 0
        self.mode_banners = 0
        self.lanes_figures = 0
        self.lane_kinds: dict[str, int] = {}
        self.confirms = 0
        self._button_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        data = dict(attrs)
        if "bw-panel" in classes:
            self.panels += 1
        if "bw-mode-banner" in classes:
            self.mode_banners += 1
        if "bw-lanes" in classes and tag == "figure":
            self.lanes_figures += 1
        if tag == "div" and "bw-lanes__lane" in classes:
            kind = data.get("data-bw-lane-kind") or ""
            self.lane_kinds[kind] = self.lane_kinds.get(kind, 0) + 1
        if "bw-numeric" in classes:
            self.numerics += 1
        if "bw-confirm" in classes:
            self.confirms = 1
        if "bw-button" in classes and tag == "button":
            self.buttons.append("")  # label captured in handle_data
            self._button_depth += 1

    def handle_data(self, payload: str) -> None:
        if self._button_depth:
            self.buttons[-1] += payload

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._button_depth:
            self._button_depth -= 1


def census(html: str) -> dict[str, Any]:
    """One served page's component census on §E.1 surfaces."""
    parser = _CensusParser()
    parser.feed(html)
    return {
        "panels": parser.panels,
        "buttons": [label.strip() for label in parser.buttons],
        "numerics": parser.numerics,
        "mode_banners": parser.mode_banners,
        "lanes_figures": parser.lanes_figures,
        "lane_kinds": dict(parser.lane_kinds),
        "confirms": parser.confirms,
    }


def _derive_for_project(
    descriptor_raw: bytes, reference: dict[str, Any] | None, descriptor_path: Path
) -> Any:
    if reference is None:
        reference = find_reference("otdp.logic_analyser/1.0.0")
    if reference is None:
        return None
    return derive_ui(descriptor_raw, reference, descriptor_path=descriptor_path)


def _page_ids(derived: Any) -> list[str]:
    return [str(page["id"]) for page in derived.manifest["pages"]]


def _assert_expect(
    expectation: dict[str, Any], censused: dict[str, dict[str, Any]]
) -> list[GateFinding]:
    """Census-vs-expect deltas, typed (record §5/5)."""
    findings: list[GateFinding] = []
    pages = sorted(censused)
    for name, row in expectation["components"].items():
        key = {
            "digital-lanes": "lanes_figures",
            "button": "buttons",
            "numeric-input": "numerics",
            "panel": "panels",
            "mode-banner": "mode_banners",
        }.get(name)
        if key is None:
            continue
        per_page = row.get("per_page")
        if per_page == "*":
            targets = {page: censused[page] for page in pages}
        elif per_page in censused:
            targets = {per_page: censused[per_page]}
        else:
            # A row without per_page pools the whole render: the count is
            # the sum across pages (panel == n_pages across all pages).
            total = 0
            for seen in censused.values():
                value = seen.get(key)
                total += len(value) if isinstance(value, list) else (value or 0)
            if total != row["count"]:
                findings.append(
                    GateFinding(
                        "classref_gate_missing"
                        if total < row["count"]
                        else "classref_gate_excess",
                        f"{name}: expected {row['count']} across the render, "
                        f"censused {total}",
                    )
                )
            continue
        for page, seen in targets.items():
            actual = seen.get(key) or 0
            if isinstance(actual, list):
                actual = len(actual)
            if actual != row["count"]:
                findings.append(
                    GateFinding(
                        "classref_gate_missing"
                        if isinstance(row["count"], int) and actual < row["count"]
                        else "classref_gate_excess",
                        f"{name} on {page}: expected {row['count']}, censused {actual}",
                    )
                )
    return findings


def _coverage_findings(
    plan: dict[str, dict[str, Any]],
    censused: dict[str, dict[str, Any]],
    declaration: dict[str, Any],
) -> tuple[list[GateFinding], list[str]]:
    """The always-on D14 coverage arm (record §5.1): per action, a rendered
    control at its ladder level OR a declared deviation. Declared
    divergences ride back as REPORTED rows; undeclared ones fail."""
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
        if level in ("L1", "L2") and slug in buttons:
            covered = level == "L1" or seen.get("numerics", 0) >= 1
        elif level == "L3":
            covered = slug in buttons or bool(buttons)
        elif level == "L4":
            covered = seen.get("lanes_figures", 0) >= 1
        divergence = bool(row.get("divergence"))
        if covered and not divergence:
            continue
        if urn in declared_ids or row.get("declared_deviation"):
            reported.append(urn)
            continue
        if divergence and not covered:
            findings.append(
                GateFinding("classref_gate_undeclared", f"{urn}: {row.get('divergence')}")
            )
        elif not covered:
            findings.append(
                GateFinding("classref_gate_uncovered", f"{urn} renders no control at {level}")
            )
    return findings, reported


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
        raise ValueError("classref_gate_reference: no reference matches this descriptor")
    validate_declaration(derived, derived.declaration)
    from .classref_gate_render import render_pages

    pages = _page_ids(derived)
    rendered = render_pages(project, pages)
    censused = {page: census(html) for page, html in rendered.items()}
    findings = _assert_expect(derived.expectation, censused)
    coverage, reported = _coverage_findings(
        derived.control_plan, censused, derived.declaration
    )
    findings.extend(coverage)
    forbidden = [
        GateFinding("classref_gate_forbidden", f"bw-confirm rendered on {page}")
        for page, seen in censused.items()
        if seen.get("confirms")
    ]
    findings.extend(forbidden)
    return GateReport(findings=tuple(findings), reported_deviations=tuple(reported))
