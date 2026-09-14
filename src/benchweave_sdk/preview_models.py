"""Immutable, JSON-safe models for deterministic UI preview data."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

PREVIEW_API_VERSION = 1

Severity = Literal["neutral", "success", "advisory", "warning", "critical", "trip"]
TimestampStrategy = Literal["fixed", "relative"]


def _finite(value: bool | int | float | str | None) -> bool | int | float | str | None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Preview observation values must be finite")
    return value


@dataclass(frozen=True, slots=True)
class PreviewObservation:
    binding_id: str
    value: bool | int | float | str | None
    unit: str | None
    quality: str
    freshness_ms: int | None
    provenance: str

    def to_document(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "value": _finite(self.value),
            "unit": self.unit,
            "quality": self.quality,
            "freshness_ms": self.freshness_ms,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class SimulatedReceipt:
    binding_id: str
    outcome: str
    message: str

    def to_document(self) -> dict[str, str]:
        return {
            "binding_id": self.binding_id,
            "outcome": self.outcome,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class PreviewScenario:
    id: str
    title: str
    description: str
    timestamp_strategy: TimestampStrategy
    observations: tuple[PreviewObservation, ...]
    permissions: frozenset[str]
    lease_state: str
    approval_state: str
    unavailable_panels: tuple[str, ...]
    expected_severity: Severity
    request_outcomes: tuple[SimulatedReceipt, ...]
    baseline: bool

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "timestamp_strategy": self.timestamp_strategy,
            "observations": [row.to_document() for row in self.observations],
            "permissions": sorted(self.permissions),
            "lease_state": self.lease_state,
            "approval_state": self.approval_state,
            "unavailable_panels": list(self.unavailable_panels),
            "expected_severity": self.expected_severity,
            "request_outcomes": [row.to_document() for row in self.request_outcomes],
            "baseline": self.baseline,
        }


@dataclass(frozen=True, slots=True)
class PreviewModel:
    plugin_id: str
    renderer_version: str
    pages: tuple[dict[str, Any], ...]
    scenarios: tuple[PreviewScenario, ...]
    simulation: bool = True

    def to_document(self) -> dict[str, Any]:
        return {
            "api_version": PREVIEW_API_VERSION,
            "plugin_id": self.plugin_id,
            "renderer_version": self.renderer_version,
            "pages": [dict(page) for page in self.pages],
            "scenarios": [scenario.to_document() for scenario in self.scenarios],
            "simulation": self.simulation,
        }
