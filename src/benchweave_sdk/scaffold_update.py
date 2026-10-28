"""Move scaffolded projects between template versions (issue #347 WS2).

``upgrade`` wraps ``copier.run_update`` pinned to the installed SDK's
version tag — template version == SDK version, so a wheel never pushes
unreleased template state from ``main``. ``adopt`` writes the provenance
record for projects scaffolded before the copier port. The answers file
``.copier-answers.yml`` is the durable provenance surface (SRF-1); both
commands refuse with STD-4 ``snake_case:`` prefixes.

The upgrade's walk contract (issue #461): the upgrade reads and writes the
git-tracked set plus what the update itself changed; it never parses ignore
rules and never traverses a symlink (a final-component symlink or Windows
junction is skipped and reported, never read or written through).
"""

from __future__ import annotations

import fnmatch
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from . import __version__
from .scaffold import (
    CANONICAL_TEMPLATE_URL,
    _enforce_lf,
    _guarded_write,
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


def _git_project_paths(project: Path) -> tuple[list[str], list[str]]:
    """Git's own view of the project's content boundary: ``(tracked, changed)``.

    ``tracked`` is ``git ls-files`` — the set the update's merge operates on
    and the author will commit; ``changed`` is ``git status --porcelain``
    taken AFTER the update ran on a clean tree, so every REPORTED
    difference from HEAD was made by the update. The reported set is a
    subset of everything the update may have written: a byte-identical
    write or a write into an ignored path stays invisible (residual D2).
    No ignore rules are parsed anywhere: git's view is the boundary
    (issue #461 §1).

    ``-z`` records are NUL-separated (no quoting, no ``core.quotePath``
    escapes); a rename/copy record carries its pre-image as the following
    field, which is consumed and dropped — the post-image path is the one
    that exists on disk. Deletions stay in the lists; the walk, not the
    parser, drops paths missing on disk. ``--untracked-files=all`` keeps a
    fully untracked directory from collapsing to a ``?? dir/`` entry the
    walk would drop (refute F1).
    """
    tracked_out = subprocess.run(  # noqa: S603, S607 — git has no in-process API
        ["git", "-C", str(project), "ls-files", "-z"],
        capture_output=True,
        check=True,
    ).stdout
    status_out = subprocess.run(  # noqa: S603, S607
        [
            "git",
            "-C",
            str(project),
            "status",
            "--porcelain",
            "-z",
            "--untracked-files=all",
        ],
        capture_output=True,
        check=True,
    ).stdout
    tracked = [name for name in tracked_out.split(b"\x00") if name]
    records = status_out.split(b"\x00")
    changed: list[bytes] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue  # the NUL-separated tail
        if b"R" in record[:2] or b"C" in record[:2]:
            index += 1  # the pre-image field of a rename/copy pair
        changed.append(record[3:])
    return (
        [name.decode("utf-8", "surrogateescape") for name in tracked],
        [name.decode("utf-8", "surrogateescape") for name in changed],
    )


def _walk_content(project: Path, relatives: list[str]) -> tuple[list[Path], list[str]]:
    """Walk project-relative paths inside the content boundary (issue #461 §2).

    A final-component symlink or Windows junction — dangling or not — is
    never project content: it is excluded from the file set and collected
    into ``skipped`` (a dangling link is a link; only a true deletion, which
    cannot be a link, is dropped silently). No ``rglob`` here: only the
    paths git knows plus what the update wrote are ever walked.
    """
    files: list[Path] = []
    skipped: list[str] = []
    for relative in relatives:
        entry = project / relative
        if entry.is_symlink() or entry.is_junction():
            skipped.append(relative)
            continue
        if not entry.exists():
            continue  # deleted on disk (a porcelain D entry)
        if entry.is_file():
            files.append(entry)
    return files, skipped


def _skip_patterns() -> list[str]:
    """The shipped template's own skip list (adversary fold B-F1).

    Parsed from our ``copier.yml`` member's single-line bracket list — the
    format this repository ships — so the restore guard needs no YAML
    dependency. Empty when the template cannot be located (the guard then
    degrades to no-op; the render-time paths have their own refusals).
    """
    from .scaffold import _packaged_template_members, _repo_template_members

    members = _packaged_template_members() or _repo_template_members() or {}
    for line in members.get("copier.yml", b"").decode("utf-8").splitlines():
        if line.startswith("_skip_if_exists:"):
            body = line.split(":", 1)[1].strip()
            if body.startswith("[") and body.endswith("]"):
                body = body[1:-1]
            return [item.strip() for item in body.split(",") if item.strip()]
    return []


def _protected_snapshot(project: Path, tracked: list[str]) -> dict[str, bytes]:
    """Skip-protected project bytes, taken before the update runs.

    copier's update DELETES project files the template no longer renders —
    skip patterns protect content, not existence — so the guard restores
    what the update removed. The snapshot walks the tracked set (the clean
    pre-update tree; an author's own committed deletion was never here to
    restore), and a symlink is never snapshotted — the restore loop can
    then never write through one.
    """
    patterns = _skip_patterns()
    if not patterns:
        return {}
    files, _skipped = _walk_content(project, tracked)
    snapshot: dict[str, bytes] = {}
    for entry in files:
        relative = entry.relative_to(project).as_posix()
        if any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
            snapshot[relative] = entry.read_bytes()
    return snapshot


def _answers_src_path(project: Path) -> str | None:
    for line in (project / ANSWERS_NAME).read_text(encoding="utf-8").splitlines():
        if line.startswith("_src_path:"):
            return line.split(":", 1)[1].strip()
    return None


def _answers_commit(project: Path) -> str | None:
    for line in (project / ANSWERS_NAME).read_text(encoding="utf-8").splitlines():
        if line.startswith("_commit:"):
            return line.split(":", 1)[1].strip() or None
    return None


def _require_target_ref(source: str, ref: str, *, role: str = "target") -> None:
    """Refuse an unresolvable template ref BEFORE copier shells git (A-F2/B-F4).

    Covers the whole tag-resolution failure class: the target tag AND the
    base ``_commit`` recorded in the answers both resolve here, so neither
    surfaces as copier's raw git pathspec traceback. A local template source
    is checked offline with rev-parse; a URL needs the same network
    round-trip the update itself would make, so ls-remote adds no new
    exposure.
    """
    if Path(source).is_dir():
        check = subprocess.run(  # noqa: S603, S607 — git has no in-process API
            ["git", "-C", source, "rev-parse", "--verify", ref],
            capture_output=True,
            text=True,
        )
        resolves = check.returncode == 0
    else:
        check = subprocess.run(  # noqa: S603, S607
            ["git", "ls-remote", source, ref],
            capture_output=True,
            text=True,
        )
        resolves = check.returncode == 0 and bool(check.stdout.strip())
    if not resolves:
        raise ValueError(
            f"upgrade_tag_missing: the {role} template ref {ref} does not resolve in "
            f"{source}; released templates only — a development install's version "
            "has no tag"
        )


def upgrade_project(
    project: Path, *, target_ref: str | None = None
) -> tuple[list[str], list[str], list[str]]:
    """Update ``project`` to the installed SDK's template tag.

    The git pre-checks (repo present, tree clean) are ours so the refusals
    carry our guidance — copier refuses the same tree on its own, belt and
    braces. ``run_update`` needs ``overwrite=True`` on copier 9.x (the
    unconditional 9.18.2 guard) and both refs must be version tags the
    template repository resolves (``upgrade_tag_missing:`` refuses an
    unresolvable one BEFORE copier shells git — a development install's
    version has no tag).

    The walk contract (issue #461): the upgrade reads and writes the
    git-tracked set plus what the update itself changed; it never parses
    ignore rules and never traverses a symlink. Ignored and untracked trees
    (a virtualenv, a build directory) produce no output; a tracked symlink
    is skipped and reported.

    Three protections wrap the update (adversary fold):

    - Skip-protected files the template DELETED are restored and reported —
      copier's update removes project files the template no longer renders,
      and skip patterns protect content, not existence.
    - Files that ended in conflict markers are reported by name — the author
      resolves both sides and commits; an update never fails on conflicts,
      and never resolves them silently.
    - Symlinks and Windows junctions are never read or written through;
      each is reported once in ``skipped``.

    Parameters
    ----------
    project
        The scaffolded project directory (its ``.copier-answers.yml`` names
        the template source and base). Resolved the way the CLI resolves it
        — copier compares canonical git prefixes.
    target_ref
        The template ref to update to. The CLI default is ``v{__version__}``
        — the installed SDK's released template tag; the parameter exists so
        the offline test lane can point at a tagged throwaway repository.

    Returns
    -------
    tuple[list[str], list[str], list[str]]
        (conflicted, restored, skipped): relative paths that ended in
        conflict markers; skip-protected files the template dropped which
        were restored to their pre-update bytes; and tracked symlinks or
        junctions the upgrade refused to traverse.

    Raises
    ------
    ValueError
        ``upgrade_answers_missing:`` (pre-copier project — adopt first),
        ``upgrade_requires_git:`` or ``upgrade_dirty_tree:`` (the 3-way
        merge needs committed history), ``upgrade_tag_missing:`` (the
        target tag does not resolve), or ``scaffold_extra_absent:``.
    """
    project = project.expanduser().resolve()
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
    source = _answers_src_path(project)
    ref = target_ref or f"v{__version__}"
    if source is not None:
        _require_target_ref(source, ref)
        base = _answers_commit(project)
        if base:
            _require_target_ref(source, base, role="base")
    # Pre-update, the clean-tree gate makes tracked == all non-ignored
    # content (§1); the porcelain half of the pair is provably empty here.
    tracked, _pre_changed = _git_project_paths(project)
    protected = _protected_snapshot(project, tracked)
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
        vcs_ref=ref,
        overwrite=True,
        quiet=True,
    )
    # Post-update on a was-clean tree, every REPORTED difference from HEAD
    # was made by the update — porcelain (with --untracked-files=all, so a
    # new directory's files are enumerated, not collapsed to "dir/") is the
    # update's visible write-set; a byte-identical write or a write into an
    # ignored path stays invisible (D2). PR #93's Windows lane normalizes
    # exactly that reported set to LF (the scaffold's output contract): an
    # author's tracked CRLF file outside the delta is never rewritten
    # (issue #461), and nothing outside the boundary is walked.
    tracked, changed = _git_project_paths(project)
    _enforce_lf(project, paths=sorted(set(changed)))
    restored = []
    for relative, content in sorted(protected.items()):
        if not (project / relative).is_file():
            # The update may have removed emptied parent directories too.
            (project / relative).parent.mkdir(parents=True, exist_ok=True)
            _guarded_write(project / relative, content)
            restored.append(relative)
    files, skipped = _walk_content(project, sorted(set(tracked) | set(changed)))
    conflicted = [
        entry.relative_to(project).as_posix()
        for entry in files
        if _CONFLICT_MARKER in entry.read_bytes()
    ]
    return conflicted, restored, skipped


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
    # is_symlink() catches a dangling link occupying the name, which exists()
    # reports as absent but through which a write would materialise the
    # link's target (the create_project destination-guard precedent).
    if answers.exists() or answers.is_symlink():
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
    # The provider variant is distinguishable by its pinned contract (issue
    # #568 row f): a provider-transport project carries the banked contract
    # beside the descriptor; the serial-stream default does not. Adoption
    # infers the shape from the tree, exactly as it infers with_ui.
    provider_transport = (project / "src" / name / "ftdi-control-provider.json").is_file()
    # Byte-exact write (Windows text mode would CRLF-ify and diverge from
    # what `new` writes on every other platform).
    answers.write_bytes(
        (
            "# Changes here will be overwritten by Copier\n"
            f"_commit: v{version}\n"
            f"_src_path: {CANONICAL_TEMPLATE_URL}\n"
            f"otdp_version: {active_version('otdp')}\n"
            f"package_name: {name}\n"
            f"provider_transport: {'true' if provider_transport else 'false'}\n"
            f"sdk_version: {version}\n"
            f"with_ui: {'true' if with_ui else 'false'}\n"
        ).encode()
    )
    return version
