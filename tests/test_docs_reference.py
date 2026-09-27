"""great-docs.yml's reference list is regenerated from the modules it claims to cover."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SURFACES = (
    "interfaces",
    "testing",
    "conformance",
    "validation",
    "presentation",
    "packaging",
    "capture",
)

# Public names deliberately left out of the rendered reference, each with its reason.
EXCLUDED = {
    "presentation.schemas": "the expanded schema map the vendored validator consumes; not an "
    "authoring entry point",
    "presentation.create_ui_resources": "the scaffold step behind `new --with-ui`; reached "
    "through the CLI, whose reference documents it",
    "validation.YankedPinWarning": "a warnings category raised by validate_descriptor on a "
    "yanked pin (issue #203 slice 1); authors catch it from the check lane, whose output "
    "renders the message — not an entry point to call",
}


def _reference_entries() -> list[str]:
    """The ``- name`` items under ``reference:`` (the repository carries no YAML parser)."""
    lines = (REPO / "great-docs.yml").read_text(encoding="utf-8").splitlines()
    start = lines.index("reference:")
    entries: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith((" ", "#")):
            break
        stripped = line.strip()
        if stripped.startswith("- ") and ":" not in stripped:
            entries.append(stripped[2:].strip())
    return entries


def _qualified(entry: str) -> str:
    """Bare names are the protocols re-exported from the package root."""
    return entry if "." in entry else f"interfaces.{entry}"


def test_every_reference_entry_resolves() -> None:
    entries = _reference_entries()
    assert entries, "no reference entries parsed"
    for entry in entries:
        module_name, _, attribute = _qualified(entry).partition(".")
        module = importlib.import_module(f"benchweave_sdk.{module_name}")
        assert hasattr(module, attribute), entry


def test_every_public_name_is_rendered_or_excluded_with_a_reason() -> None:
    rendered = {_qualified(entry) for entry in _reference_entries()}
    public: set[str] = set()
    for surface in SURFACES:
        module = importlib.import_module(f"benchweave_sdk.{surface}")
        for name, value in vars(module).items():
            # callable(), not isfunction(): a @cache-wrapped function is public too.
            if name.startswith("_") or not callable(value):
                continue
            if getattr(value, "__module__", None) == module.__name__:
                public.add(f"{surface}.{name}")
    assert public - rendered - set(EXCLUDED) == set(), "public but neither rendered nor excluded"
    assert set(EXCLUDED) & rendered == set(), "excluded names must not also be rendered"
    assert set(EXCLUDED) <= public, "an exclusion names something that no longer exists"
    assert rendered <= public, "a rendered name is not a public name of its module"


def test_every_rendered_name_has_a_docstring() -> None:
    """A rendered entry with no docstring ships as a bare signature."""
    for entry in _reference_entries():
        module_name, _, attribute = _qualified(entry).partition(".")
        target = getattr(importlib.import_module(f"benchweave_sdk.{module_name}"), attribute)
        assert inspect.getdoc(target), entry
