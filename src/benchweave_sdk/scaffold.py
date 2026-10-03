"""Generate a standalone, read-only synthetic plugin; never contact hardware.

The project content lives in the copier template at the repository root
(``copier.yml`` + ``template/``), packaged into the wheel at
``benchweave_sdk/scaffold_template/`` (PKG-2 force-include). This module owns
the render orchestration: guards, staging, the answers pin that records
provenance, and the post-render descriptor validation. Byte parity between
the template render and the committed fixture is pinned by
``tests/test_scaffold_copier.py`` (R-2).
"""

from __future__ import annotations

import json
import keyword
import re
import shutil
import sys
import tempfile
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from . import __version__
from .served import active_version
from .validation import validate_descriptor

# A generated project whose package shadows the SDK itself or a stdlib module
# breaks its own install and tests; deny those names up front.
RESERVED_PACKAGE_NAMES = frozenset({"benchweave", "benchweave_sdk"}) | frozenset(
    sys.stdlib_module_names
)

# The canonical copier template source (issue #347 WS2): the tagged SDK
# repository itself. `new` renders from a packaged copy offline; this URL is
# what the answers pin records so a scaffolded project can later update
# against released template tags (template version == SDK version).
CANONICAL_TEMPLATE_URL = "https://github.com/madeinoz67/benchweave-sdk"


def _load_copier() -> Any:
    """The copier entry point, or a refusal naming the install command.

    Copier rides the optional ``[scaffold]`` extra (the signing-extra
    precedent): the base install never gains the copier dependency tree, and
    its absence refuses with a machine-matchable prefix instead of a traceback.
    """
    try:
        from copier import run_copy
    except ImportError as exc:  # covered by the extra-absent refusal test
        raise ValueError(
            "scaffold_extra_absent: project scaffolding needs the optional extra "
            "(pip install benchweave-sdk[scaffold])"
        ) from exc
    return run_copy


def _sdk_checkout_root() -> Path | None:
    """The SDK repository checkout containing this module, or None when installed.

    Same twin-halves rule as ``cli._sdk_checkout_root`` (repo mode for
    ``sync-standards``): the grandparent directory is a checkout whose
    pyproject names this project AND this module runs from that checkout's
    ``src`` tree. Duplicated here because cli imports this module; the sync
    lane's copy is the reference.
    """
    from .validation import _project_name

    package_dir = Path(__file__).resolve().parent
    candidate = package_dir.parents[1]
    if _project_name(candidate) != "benchweave-sdk":
        return None
    if package_dir != candidate / "src" / "benchweave_sdk":
        return None
    return candidate


def _traversable_members(node: Traversable, prefix: str = "") -> list[tuple[str, bytes]]:
    members: list[tuple[str, bytes]] = []
    for child in node.iterdir():
        if child.is_dir():
            members.extend(_traversable_members(child, prefix + child.name + "/"))
        else:
            members.append((prefix + child.name, child.read_bytes()))
    return members


def _packaged_template_members() -> dict[str, bytes] | None:
    """The wheel's force-included template (PKG-2), or None in a source checkout."""
    base = files("benchweave_sdk") / "scaffold_template"
    if not (base / "copier.yml").is_file():
        return None
    members: dict[str, bytes] = {"copier.yml": (base / "copier.yml").read_bytes()}
    members.update(
        ("template/" + relative, content)
        for relative, content in _traversable_members(base / "template")
    )
    return members


def _repo_template_members() -> dict[str, bytes] | None:
    """The checkout's working-tree template (dev/test mode), or None when installed."""
    root = _sdk_checkout_root()
    if root is None or not (root / "copier.yml").is_file() or not (root / "template").is_dir():
        return None
    members = {"copier.yml": (root / "copier.yml").read_bytes()}
    for path in (root / "template").rglob("*"):
        if path.is_file():
            members["template/" + path.relative_to(root / "template").as_posix()] = (
                path.read_bytes()
            )
    return members


def _materialize_template(scratch: Path) -> Path:
    """Write the template members into ``scratch``; return the template root.

    copier is never pointed at this repository's checkout: a git-backed
    ``src_path`` makes it clone HEAD, so uncommitted template bytes would
    silently vanish from a repo-mode render. The materialized copy is also
    the exact layout the wheel force-includes, so repo mode and installed
    mode render from the same shape — and parity tests see working-tree
    template bytes, not the last commit's.
    """
    members = _packaged_template_members()
    if members is None:
        members = _repo_template_members()
    if members is None:
        raise ValueError(
            "scaffold_template_missing: the copier template is neither packaged with "
            "this install nor present in a repository checkout; reinstall "
            "benchweave-sdk[scaffold]"
        )
    root = scratch / "scaffold_template"
    for relative, content in members.items():
        member = root / relative
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(content)
    return root


def _pin_answers(project: Path, sdk_version: str) -> None:
    """Rewrite the fresh answers file's provenance lines to durable values.

    The render happened from a materialized copy of the packaged template —
    an ephemeral directory — so copier records that path as ``_src_path`` and
    (the copy is not a git repository) records no ``_commit`` at all. Both
    lines are replaced here: the canonical repository URL and the template
    tag that matches the running SDK version (template version == SDK
    version). Line-level rewrites on a file whose shape the render just
    produced — no YAML dependency, no silent substitution.
    """
    answers = project / ".copier-answers.yml"
    if not answers.is_file():
        # The template must ship .copier-answers.yml.jinja; without it copier
        # writes no provenance at all and a scaffolded project can never update.
        raise ValueError(
            "scaffold_answers_missing: the template does not render .copier-answers.yml; "
            "the answers-file template member is required"
        )
    rendered = answers.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in rendered if not line.startswith(("_commit:", "_src_path:"))]
    insert_at = 1 if kept and kept[0].startswith("#") else 0
    kept[insert_at:insert_at] = [
        f"_commit: v{sdk_version}\n",
        f"_src_path: {CANONICAL_TEMPLATE_URL}\n",
    ]
    # Byte-exact write: Path.write_text opens text mode, and text mode
    # translates \n to os.linesep — CRLF on Windows, which would break the
    # R-2 byte-parity comparison against the LF fixture on that lane.
    answers.write_bytes("".join(kept).encode())


_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\s*\[[^\]]*\])?"
    r"\s*==\s*(?P<version>\S+)$"
)
_VERSION_RE = re.compile(
    r"^[Vv]?(?P<release>\d+(?:\.\d+)*)"
    r"(?P<rest>(?:\.?[A-Za-z][0-9A-Za-z.]*)?(?:\+[0-9A-Za-z.]+)?)$"
)


def _normalize_version(version: str) -> str | None:
    """Normalize a version for comparison; None when not version-shaped.

    PEP 440-lite (issue #347 WS1b refute F2): strips one leading ``v`` and
    zero-pads the release to three dot-separated parts, so ``0.5`` and
    ``0.5.0`` compare equal. Text without a leading numeric release
    (``..++--``) is not version-shaped and returns None.
    """
    match = _VERSION_RE.match(version.strip())
    if match is None:
        return None
    parts = match["release"].split(".")
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts) + match["rest"]


def _requirement_pin(requirement: str) -> str | None:
    """The normalized ``==`` version of a benchweave-sdk requirement line.

    Tolerates the PEP 508 spellings a hand-edited line realistically carries
    (refute F1): an extras clause (``benchweave-sdk[signing]==0.5.0``), an
    environment marker after ``;``, whitespace around ``==``, and PEP 503
    name normalization (``BenchWeave-SDK``, ``benchweave_sdk``). Returns None
    when the line names another distribution, carries no ``==`` pin, or its
    version is not version-shaped.
    """
    match = _PIN_RE.match(requirement.split(";", 1)[0].strip())
    if match is None:
        return None
    if re.sub(r"[-_.]+", "-", match["name"]).lower() != "benchweave-sdk":
        return None
    return _normalize_version(match["version"])


def recorded_sdk_version(project: Path) -> str | None:
    """The normalized SDK version pin recorded in ``project``.

    ``create_project`` writes ``benchweave-sdk==<version>`` into the
    generated ``[project.optional-dependencies]`` test extra. That line is
    the requirement ``new`` writes — a mutable declaration the author may
    later edit, not an immutable provenance record (issue #347 WS1b). The
    durable provenance is ``.copier-answers.yml`` (WS2).

    Parameters
    ----------
    project
        Project directory whose ``pyproject.toml`` carries the pin.

    Returns
    -------
    str | None
        The pinned version, normalized (leading ``v`` stripped, release
        zero-padded to three parts), or None when the project has no
        ``pyproject.toml`` or no version-shaped ``benchweave-sdk==`` pin in
        its test extra. Hand-edited PEP 508 spellings — an extras clause,
        an environment marker, whitespace around ``==``, PEP 503 name case
        — still record. When the extra lists several ``benchweave-sdk``
        requirements, the first one with a version-shaped ``==`` pin wins.

    Raises
    ------
    ValueError
        If ``pyproject.toml`` exists but cannot be parsed.
    """
    pyproject = project / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        with pyproject.open("rb") as handle:
            document: dict[str, Any] = tomllib.load(handle)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ValueError(f"pyproject_unreadable: {pyproject}: {exc}") from exc
    section = document.get("project")
    extras = section.get("optional-dependencies") if isinstance(section, dict) else None
    test_extra = extras.get("test") if isinstance(extras, dict) else None
    if not isinstance(test_extra, list):
        return None
    for requirement in test_extra:
        if isinstance(requirement, str):
            version = _requirement_pin(requirement)
            if version is not None:
                return version
    return None


def create_project(destination: Path, package: str, *, with_ui: bool = False) -> None:
    """Write a complete synthetic plugin project under ``destination``.

    Renders the copier template (``pyproject.toml``, a README, ``AI-GUIDE.md``,
    a working read-only adapter with its synthetic protocol, a validated
    ``descriptor.json``, synthetic protocol evidence, a pytest suite, and the
    seeded skills), then pins ``.copier-answers.yml`` to the canonical
    repository and this SDK's template tag so the project stays updatable.
    Nothing generated contacts hardware or claims qualification.

    Parameters
    ----------
    destination
        Project directory to create; it must not already exist.
    package
        Lowercase package name (``[a-z][a-z0-9_]*``) that does not
        shadow the SDK or a stdlib module.
    with_ui
        Records the ``--with-ui`` intent in the answers file for provenance.
        The UI resources themselves are derived from the descriptor's exact
        bytes by ``presentation.create_ui_resources`` after the project lands
        — SDK code, deliberately not template content.

    Raises
    ------
    ValueError
        If the package name is invalid or reserved, the ``[scaffold]`` extra
        is absent (``scaffold_extra_absent:``), or the template renders an
        invalid descriptor.
    FileExistsError
        If the destination directory — or a leftover ``.partial`` staging
        sibling — already exists; a dangling symlink occupying either name
        counts as existing.

    Examples
    --------
    >>> from pathlib import Path
    >>> from benchweave_sdk.scaffold import create_project
    >>> create_project(Path("plugins/acme/cooler"), "acme_cooler")
    """
    if (
        not re.fullmatch(r"[a-z][a-z0-9_]*", package)
        or keyword.iskeyword(package)
        or package in RESERVED_PACKAGE_NAMES
    ):
        raise ValueError(
            "Use a lowercase Python package name that does not shadow the SDK or the stdlib"
        )
    # is_symlink() catches a dangling symlink occupying the name, which
    # exists() reports as absent but which would break the final rename.
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage into a sibling directory and rename at the end, so an interrupted
    # run never leaves a half-generated project at the destination. A
    # pre-existing staging path is refused, never deleted: it is either not
    # ours (the tool must not destroy content it did not create) or the
    # leftover of a hard-killed run, which the operator removes deliberately.
    staging = destination.with_name(destination.name + ".partial")
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(f"Staging path already exists: {staging}; remove it and retry")
    # Resolve the optional extra before the first write: a refused scaffold
    # leaves neither the destination nor the staging sibling behind (a
    # pre-existing parent directory is not undone — mkdir(parents=True) is
    # idempotent and destroys nothing).
    run_copy = _load_copier()
    staging.mkdir()
    try:
        # tempfile resolves macOS's /tmp symlink; copier's own git plumbing
        # compares canonical prefixes and refuses mixed spellings.
        with tempfile.TemporaryDirectory() as scratch:
            template_root = _materialize_template(Path(scratch).resolve())
            run_copy(
                str(template_root),
                str(staging),
                data={
                    "package_name": package,
                    "with_ui": with_ui,
                    "sdk_version": __version__,
                    "otdp_version": active_version("otdp"),
                },
                defaults=True,
                quiet=True,
            )
        _pin_answers(staging, __version__)
        # Generate-time validation contract (previously descriptor_for's
        # dict-level check): a template edit that would render an invalid
        # descriptor fails here, before the project lands.
        rendered = json.loads(
            (staging / "src" / package / "descriptor.json").read_text(encoding="utf-8")
        )
        validate_descriptor(rendered)
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
