"""The host presentation model (I2a §3.1): one projection, reused.

The standalone host renders the plugin's ALREADY-VALIDATED presentation
documents — the same :func:`benchweave_sdk.presentation.load_validated_preview_inputs`
the loader ran at startup, now called with THIS host's declared feature and
panel sets (SW-41). The host writes no second projection of the manifest:
page rows come from the manifest, plot views come from the SDK's own
``project_plot_views`` verbatim, and the reading tiles render through the
installed ``benchweave-ui-html`` partials — the exact components the
contract harness pins (Q2's re-derived oracle).

The quality→severity map is DATA, closed over the live pipeline's read
quality vocabulary and pinned by test against ``generate_baselines``' own
``expected_severity`` rows: the SDK's baseline model is the authority and
the two tables cannot drift silently. An unknown quality string (a real
device's own vocabulary) renders neutral severity with the string verbatim
in the quality slot — never a guess (ST-3's two-channels rule).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from benchweave_ui_html.data import (
    ModeBannerData,
    ModeEntry,
    ReadingData,
    Severity,
)
from benchweave_ui_html.fixtures import MODES
from benchweave_ui_html.partials import render_mode_banner, render_reading
from benchweave_ui_html.staleness import staleness

from benchweave_sdk.fixtures import project_plot_views
from benchweave_sdk.presentation import (
    ValidatedPreviewInputs,
    check_ui,
    load_validated_preview_inputs,
)
from benchweave_sdk.preview_models import PlotView

if TYPE_CHECKING:  # pragma: no cover - typing only, breaks the import cycle
    from pathlib import Path

#: What this host renders, declared (SW-41). A manifest whose
#: ``required_ui_features`` names an id outside this set refuses at load
#: with ``unsupported_feature`` — the honest refusal, not a silent page.
SUPPORTED_FEATURES: frozenset[str] = frozenset(
    {
        "pages.readings",
        "pages.configuration",
        "pages.dataset",
        "plots.time-series",
        "plots.waveform",
        "plots.digital-lanes",
        "staleness-verdicts",
    }
)

#: The host ships no class/custom panel: every panel page renders the
#: ``panel_unavailable`` disclosure (optional ones) or refuses the load
#: (required ones) — never a guessed rendering of a panel it does not have.
SUPPORTED_PANELS: frozenset[str] = frozenset()

#: The closed quality→severity map over the live pipeline's vocabulary.
#: ``disconnected`` never appears as a read quality (the read refuses —
#: the refused state composes critical through :func:`refusal_severity`);
#: it is a key so the pinned test can drive the baseline row directly.
QUALITY_SEVERITY: dict[str, Severity] = {
    "valid": "neutral",
    "loading": "neutral",
    "stale": "advisory",
    "disconnected": "critical",
    "warning": "warning",
    "critical": "critical",
    "trip": "trip",
    "recovering": "success",
}

#: Page-level composition order (worst-of): a protective trip outranks a
#: critical fault, which outranks a warning — the tile severities are the
#: §B.1 keys and the page composes the most severe contributor. The rank
#: is host composition data, pinned end to end by the baseline parity test
#: (``generate_baselines`` rows) in ``tests/server/test_parity.py``.
SEVERITY_RANK: dict[Severity, int] = {
    "neutral": 0,
    "success": 1,
    "advisory": 2,
    "warning": 3,
    "critical": 4,
    "trip": 5,
}

#: A test-only discrimination hook (the parity suite's bypass-tile RED
#: control): ``False`` renders the I1-era hand-rolled tile instead of the
#: package partial, and the component-parity arm must RED — proving the
#: suite discriminates a hand-rolled tile from the partial's exact output.
PARTIAL_TILES: bool = True


def compose_severity(parts: list[Severity]) -> Severity:
    """The worst contributor; an empty page composes neutral."""
    if not parts:
        return "neutral"
    return max(parts, key=lambda severity: SEVERITY_RANK[severity])


def refusal_severity(code: str, adapter: Mapping[str, Any] | None) -> Severity:
    """What a refused read contributes to the page severity.

    The SDK's own baseline rows are the authority: a device REJECTION
    (``request-rejected``) is a warning — the device answered no against
    its own state — while every other refusal (the transport is gone, the
    adapter degraded: the ``disconnected`` state) composes critical, the
    observation channel being down.
    """
    if code == "conflict" and adapter is not None and adapter.get("code") == "DEVICE_REJECTED":
        return "warning"
    return "critical"


# --- the §D.1 mode banner ------------------------------------------------------


def mode_banner_entries(*, simulated: bool) -> ModeBannerData:
    """The banner entries in §D.1's fixed order: the three standalone
    truths always, ``simulated`` iff the transport is the mock (#309-B's
    rule carried onto the one contract component). The wordings are the
    package's own §D.1 mode-row literals — import-compared, never copied."""
    entries = tuple(
        ModeEntry(key=entry.key, wording=entry.wording)
        for entry in MODES
        if entry.key != "simulated" or simulated
    )
    return ModeBannerData(modes=entries)


def mode_banner_html(*, simulated: bool) -> str:
    return render_mode_banner(mode_banner_entries(simulated=simulated))


# --- the reading tile ----------------------------------------------------------


def value_text(value: Any) -> str:
    """The tile's value string: an absent value renders the em dash — never
    ``None`` (a Python artifact on a device page) and never a blank."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def freshness_text(age_ms: Any) -> str:
    """The tile's freshness line (the composition fixture's own format)."""
    if age_ms is None:
        return "Unavailable"
    return f"{float(age_ms):g} ms"


def descriptor_max_age_ms(parameter: Mapping[str, Any]) -> float | None:
    """The parameter's own read-acceptance window (ST-1: the descriptor's
    ``read_policy.max_age_ms``, never a host default; absent ⇒ no verdict)."""
    policy = parameter.get("read_policy")
    if not isinstance(policy, Mapping):
        return None
    raw = policy.get("max_age_ms")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def reading_tile_html(
    read: Mapping[str, Any] | None,
    parameter: Mapping[str, Any],
    *,
    label: str,
) -> tuple[str, Severity]:
    """Render one reading tile through the package partial.

    ``read`` is the seam's ``parameter_read`` result (``None`` renders the
    disconnected tile: no value, no freshness). Returns the tile HTML and
    the severity the tile contributes to the page composition.
    """
    quality = str((read or {}).get("quality") or "")
    severity: Severity = QUALITY_SEVERITY.get(quality, "neutral")
    age_ms = (read or {}).get("age_ms")
    fresh = (
        float(age_ms)
        if isinstance(age_ms, (int, float)) and not isinstance(age_ms, bool)
        else None
    )
    verdict = staleness(fresh, descriptor_max_age_ms(parameter))
    unit = (read or {}).get("unit") or parameter.get("unit") or ""
    if PARTIAL_TILES:
        data = ReadingData(
            label=label,
            severity=severity,
            value=value_text((read or {}).get("value")),
            unit=str(unit),
            quality=quality or "unavailable",
            freshness=freshness_text(age_ms),
            stale_verdict=verdict,
        )
        return render_reading(data), severity
    # The I1-era hand-rolled row (the bypass-tile RED control's render).
    value = (read or {}).get("value")
    hand = (
        f'<tr><th scope="row">{label}</th><td class="value">{value}</td>'
        f"<td>{unit}</td><td>{quality}</td></tr>"
    )
    return hand, severity


# --- the page model ------------------------------------------------------------


@dataclass(frozen=True)
class BindingRow:
    """One manifest binding resolved against the binding catalogue."""

    id: str
    kind: str
    target_id: str
    parameter_id: str | None = None


@dataclass(frozen=True)
class PageView:
    """One manifest page, renderer-ready."""

    id: str
    title: str
    kind: str
    required: bool
    panel_id: str | None
    bindings: tuple[BindingRow, ...]


def _page_views(
    manifest: Mapping[str, Any], catalogue_doc: Mapping[str, Any]
) -> tuple[PageView, ...]:
    targets = {
        str(target.get("id")): target
        for target in catalogue_doc.get("targets", [])
        if isinstance(target, Mapping)
    }
    bindings = {
        str(row.get("id")): row
        for row in manifest.get("bindings", [])
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    views: list[PageView] = []
    for page in manifest.get("pages", []):
        rows: list[BindingRow] = []
        for name in page.get("bindings", []):
            binding = bindings.get(str(name), {})
            target = targets.get(str(binding.get("target_id")), {})
            rows.append(
                BindingRow(
                    id=str(name),
                    kind=str(binding.get("kind", "")),
                    target_id=str(binding.get("target_id", "")),
                    parameter_id=(
                        str(target["parameter_id"])
                        if isinstance(target.get("parameter_id"), str)
                        else None
                    ),
                )
            )
        panel_id = page.get("panel_id")
        views.append(
            PageView(
                id=str(page["id"]),
                title=str(page["title"]),
                kind=str(page["kind"]),
                required=bool(page.get("required")),
                panel_id=str(panel_id) if isinstance(panel_id, str) else None,
                bindings=tuple(rows),
            )
        )
    return tuple(views)


class HostPresentation:
    """The validated presentation, projected once at app construction."""

    def __init__(self, *, package_dir: Path, has_presentation: bool) -> None:
        self._inputs: ValidatedPreviewInputs | None = None
        self.unavailable_pages: tuple[str, ...] = ()
        if not has_presentation:
            self.pages: tuple[PageView, ...] = ()
            self.plot_views: tuple[PlotView, ...] = ()
            return
        presentation_path = package_dir / "presentation.json"
        descriptor_path = package_dir / "descriptor.json"
        catalogue_path = package_dir / "binding-catalogue.json"
        # ``check_ui`` is the public carrier of ``unavailable_pages`` (the
        # page-level disclosure); ``load_validated_preview_inputs`` is the
        # validated model itself. Two public calls at construction — the
        # loader already ran the validation at startup (SW-05), and this
        # module refuses to reach for the SDK's private loader to save one
        # parse of the same small documents.
        report = check_ui(
            presentation_path,
            descriptor_path,
            package_dir,
            catalogue_path,
            firmware=None,
            features=SUPPORTED_FEATURES,
            panels=SUPPORTED_PANELS,
        )
        inputs = load_validated_preview_inputs(
            presentation_path,
            descriptor_path,
            package_dir,
            catalogue_path,
            firmware=None,
            features=SUPPORTED_FEATURES,
            panels=SUPPORTED_PANELS,
        )
        self._inputs = inputs
        self.unavailable_pages = tuple(report.unavailable_pages)
        self.pages = _page_views(inputs.manifest, inputs.binding_catalogue)
        self.plot_views = project_plot_views(inputs)

    @property
    def available(self) -> bool:
        """Whether the plugin declared presentation documents."""
        return self._inputs is not None

    @property
    def manifest(self) -> Mapping[str, Any]:
        assert self._inputs is not None, "no presentation documents"
        return self._inputs.manifest

    @property
    def binding_catalogue(self) -> Mapping[str, Any]:
        assert self._inputs is not None, "no presentation documents"
        return self._inputs.binding_catalogue

    def page(self, page_id: str) -> PageView | None:
        for view in self.pages:
            if view.id == page_id:
                return view
        return None


def load_host_presentation(plugin: Any) -> HostPresentation:
    """Build the host presentation for one loaded plugin (test seam)."""
    return HostPresentation(
        package_dir=plugin.package_dir, has_presentation=plugin.has_presentation
    )
