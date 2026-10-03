"""Move scaffolded projects between template versions (issue #347 WS2).

``upgrade`` wraps ``copier.run_update`` pinned to the installed SDK's
version tag — template version == SDK version, so a wheel never pushes
unreleased template state from ``main``. ``adopt`` writes the provenance
record for projects scaffolded before the copier port. The answers file
``.copier-answers.yml`` is the durable provenance surface (SRF-1); both
commands refuse with STD-4 ``snake_case:`` prefixes.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

from . import __version__
from .scaffold import (
    CANONICAL_TEMPLATE_URL,
    _normalize_version,
    recorded_sdk_version,
)
from .served import active_version

ANSWERS_NAME = ".copier-answers.yml"
_CONFLICT_MARKER = b"<<<<<<<"


def _load_run_update() -> Any:
    """The copier update entry point, with the [scaffold]-extra refusal
    (same shape as ``scaffold._load_copier``; that one returns ``run_copy``)."""
    try:
        from copier import run_update
    except ImportError as exc:  # covered by the extra-absent refusal test
        raise ValueError(
            "scaffold_extra_absent: project scaffolding needs the optional extra "
            "(pip install benchweave-sdk[scaffold])"
        ) from exc
    return run_update


def _project_files(project: Path) -> list[Path]:
    return [
        entry
        for entry in sorted(project.rglob("*"))
        if entry.is_file() and ".git" not in entry.relative_to(project).parts
    ]


def upgrade_project(project: Path, *, target_ref: str | None = None) -> list[str]:
    """Update ``project`` to the installed SDK's template tag.

    The git pre-checks (repo present, tree clean) are ours so the refusals
    carry our guidance — copier refuses the same tree on its own, belt and
    braces. ``run_update`` needs ``overwrite=True`` on copier 9.x (the
    unconditional 9.18.2 guard) and both refs must be version tags the
    template repository resolves. Returns the relative paths that ended in
    conflict markers: the author resolves both sides and commits — an
    update never fails on conflicts, and never resolves them silently.

    Parameters
    ----------
    project
        The scaffolded project directory (its ``.copier-answers.yml`` names
        the template source and base).
    target_ref
        The template ref to update to. The CLI default is ``v{__version__}``
        — the installed SDK's released template tag; the parameter exists so
        the offline test lane can point at a tagged throwaway repository.

    Raises
    ------
    ValueError
        ``upgrade_answers_missing:`` (pre-copier project — adopt first),
        ``upgrade_requires_git:`` or ``upgrade_dirty_tree:`` (the 3-way
        merge needs committed history), or ``scaffold_extra_absent:`` (the
        copier extra is not installed).
    """
    if not (project / ANSWERS_NAME).is_file():
        raise ValueError(
            "upgrade_answers_missing: no .copier-answers.yml in this project; "
            "pre-copier projects run 'benchweave-sdk adopt' first, or scaffold "
            "with 'benchweave-sdk new'"
        )
    if not (project / ".git").exists():
        raise ValueError(
            "upgrade_requires_git: the update's 3-way merge needs committed "
            "history; run 'git init && git add -A && git commit -m \"pre-upgrade "
            "state\"' first ('new' deliberately does not git-init)"
        )
    status = subprocess.run(  # noqa: S603, S607 — git has no in-process API
        ["git", "-C", str(project), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise ValueError(
            "upgrade_requires_git: not a usable git repository "
            f"({status.stderr.strip()[:160] or 'git failed'})"
        )
    if status.stdout.strip():
        raise ValueError(
            "upgrade_dirty_tree: commit or stash your changes before upgrading "
            "(copier refuses the same tree): " + status.stdout.strip()[:200]
        )
    run_update = _load_run_update()
    run_update(
        str(project),
        data={
            # Refresh the version-bearing renders to the installed SDK; the
            # stored answers alone would re-render the old pin.
            "sdk_version": __version__,
            "otdp_version": active_version("otdp"),
        },
        defaults=True,
        vcs_ref=target_ref or f"v{__version__}",
        overwrite=True,
        quiet=True,
    )
    return [
        entry.relative_to(project).as_posix()
        for entry in _project_files(project)
        if _CONFLICT_MARKER in entry.read_bytes()
    ]


def _inferred_package(project: Path) -> str | None:
    """The package name from the generated ``packages = ["src/<pkg>"]`` shape."""
    pyproject = project / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        with pyproject.open("rb") as handle:
            document: dict[str, Any] = tomllib.load(handle)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ValueError(
            f"adopt_provenance_unknown: pyproject.toml is unreadable ({exc}); "
            "pass --package explicitly"
        ) from exc
    tool: Any = document.get("tool")
    hatch: Any = tool.get("hatch") if isinstance(tool, dict) else None
    targets: Any = hatch.get("build", {}).get("targets") if isinstance(hatch, dict) else None
    wheel: Any = targets.get("wheel") if isinstance(targets, dict) else None
    packages: Any = wheel.get("packages") if isinstance(wheel, dict) else None
    if (
        isinstance(packages, list)
        and len(packages) == 1
        and isinstance(packages[0], str)
        and packages[0].startswith("src/")
    ):
        return packages[0][len("src/") :]
    return None


def adopt_project(
    project: Path, *, package: str | None = None, scaffolded_at: str | None = None
) -> str:
    """Write ``.copier-answers.yml`` for a project scaffolded pre-copier.

    The claim the record makes is explicit: this tree equals a template@vN
    render plus author edits. That claim is sound for trees inside the
    parity back-check window (v0.4.1 forward, R-2); for older shapes the
    failure direction is the safe one — deltas attribute to the author and
    survive, conflicts are loud, nothing is lost. The base version comes
    from the generated test-extra pin (``recorded_sdk_version``, WS1b) or
    ``--scaffolded-at``; an unknown base is never claimed silently.

    Parameters
    ----------
    project
        The scaffolded project directory; must not already carry answers.
    package
        Override for the package name (default: inferred from pyproject).
    scaffolded_at
        Override for the scaffolding SDK version (default: the pyproject
        pin) — for projects whose pin the author already moved.

    Returns
    -------
    str
        The normalized version the answers were written against.

    Raises
    ------
    ValueError
        ``adopt_answers_present:`` (already adopted), or
        ``adopt_provenance_unknown:`` (package or base version not
        derivable and not overridden).
    """
    answers = project / ANSWERS_NAME
    if answers.exists():
        raise ValueError(
            "adopt_answers_present: this project already carries "
            ".copier-answers.yml; adopt is for pre-copier projects only"
        )
    name = package or _inferred_package(project)
    if name is None:
        raise ValueError(
            "adopt_provenance_unknown: cannot infer the package name from "
            "pyproject.toml (expected packages = [\"src/<pkg>\"]); pass --package"
        )
    if scaffolded_at is not None:
        version = _normalize_version(scaffolded_at)
        if version is None:
            raise ValueError(
                f"adopt_provenance_unknown: --scaffolded-at {scaffolded_at!r} is "
                "not version-shaped"
            )
    else:
        version = recorded_sdk_version(project)
        if version is None:
            raise ValueError(
                "adopt_provenance_unknown: no version-shaped benchweave-sdk== pin "
                "in [project.optional-dependencies] test; pass --scaffolded-at "
                "with the SDK version that scaffolded this project"
            )
    with_ui = (project / "UI-GUIDE.md").is_file()
    answers.write_text(
        "# Changes here will be overwritten by Copier\n"
        f"_commit: v{version}\n"
        f"_src_path: {CANONICAL_TEMPLATE_URL}\n"
        f"otdp_version: {active_version('otdp')}\n"
        f"package_name: {name}\n"
        f"sdk_version: {version}\n"
        f"with_ui: {'true' if with_ui else 'false'}\n",
        encoding="utf-8",
    )
    return version
