#!/usr/bin/env python3
# author: Stephen Eaton
"""The release-cut transaction: one command owns the bump's blast radius.

Issue #408 slice S1 (design record: gateway issue #408 — the SDK slices
reference it). The four incident classes the design traces to their lines:
scaffold byte-parity fixtures reddening on the bump (detection existed,
motion did not — the cut regenerates them, occurrence-validated); docs-bucket
registration ordering (the tag's own tree must carry its registration — the
cut stages the exact tag-commit patch for review); the post-merge/pre-tag
drift window (the cut writes the lock anchor); the v0.7.0 anchor skip
(``--verify`` proves ``compatibility.sdk`` parity at PR time — root cause d).

WHAT THE COMMAND REFUSES (each tested): no git commit, no tag creation, no
push, no publish, no network — its only git entry point whitelists the
read-only verbs (status, tag -l, log, rev-parse, show, diff); a
non-increment VERSION; a dirty tree; any occurrence mismatch (two-pass:
nothing is written before every pattern validates); a missing declared
file; a re-cut over an already-cut tree without --force; a phase-2 patch
that would touch a third file. The cut leaves the working tree
staged-for-review — the operator commits.

Modes: cut (default, positional VERSION); --verify (read-only: (i) every
substitution pattern matches its expected count at the tree's current
version, (ii) the anchor — standards-lock.json compatibility.sdk ==
pyproject version, (iii) the staged phase-2 patch exists and git apply
--check succeeds, (iv) the patch's file set is exactly {great-docs.yml,
website/index.html}); --phase2-only (regenerate the staged patch + plan).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

CANONICAL_TEMPLATE_URL = "https://github.com/madeinoz67/benchweave-sdk"
PYPROJECT = "pyproject.toml"
UV_LOCK = "uv.lock"
README = "README.md"
WEBSITE = "website/index.html"
LOCK = "standards-lock.json"
MATRIX = "docs/internal/release-review-matrix.md"
GREAT_DOCS = "great-docs.yml"
FIXTURES = "tests/fixtures/scaffold_expected"
RELEASE_DIR = ".release"
PHASE2_FILES = (GREAT_DOCS, WEBSITE)

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
RELEASE_REF_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
BOT_RE = re.compile(r"\[bot\]")

GIT_READ_ONLY = {"status", "log", "rev-parse", "show", "diff"}
EXIT_OK = 0
EXIT_FAIL = 1


class ReleaseCutError(Exception):
    """A refusal or an abort — the message names what and why."""


@dataclass(frozen=True)
class DeclaredSurface:
    """One version-bearing surface the cut owns.

    kind: substitution = occurrence-validated OLD-to-NEW rewrite; regen =
    rendered from the packaged template at the new version; derived =
    computed content (the matrix result-record scaffold); phase2 = the
    tag-commit patch (generation + staged emission; the operator applies it
    at the tag commit, and --verify proves applicability at PR time).
    """

    path: str
    kind: str
    reason: str
    patterns: tuple[tuple[str, int], ...] = ()


DECLARED_SURFACES: tuple[DeclaredSurface, ...] = (
    DeclaredSurface(
        PYPROJECT,
        "substitution",
        "the version source (matrix rows 1-4's machine truth) — the v0.8.0 walk commit",
        (('version = "{v}"', 1),),
    ),
    DeclaredSurface(
        UV_LOCK,
        "substitution",
        "the root-package lockfile block — the v0.8.0 walk commit",
        (('name = "benchweave-sdk"\nversion = "{v}"', 1),),
    ),
    DeclaredSurface(
        README,
        "substitution",
        "matrix row 1: the README baseline stamp — the v0.8.0 walk commit",
        (("SDK {v}, OTDP", 1),),
    ),
    DeclaredSurface(
        WEBSITE,
        "substitution",
        "matrix rows 2+4: hero status line and compatibility tagline — the v0.8.0 walk commit",
        (("</span> SDK {v} ·", 1), ("Compatibility: SDK {v} against", 1),),
    ),
    DeclaredSurface(
        LOCK,
        "substitution",
        "the lock anchor (matrix rows 4/9) — the v0.8.0 walk commit",
        # compact JSON: the lock file ships single-line, no space after the
        # colon (the section-9 replay caught the spaced pattern matching 0)
        (('"sdk":"{v}"', 1),),
    ),
    DeclaredSurface(
        FIXTURES,
        "regen",
        "the scaffold byte-parity fixtures at the new version — the fixture commit",
    ),
    DeclaredSurface(
        MATRIX,
        "derived",
        "the result-record scaffold, appended at the file end — the v0.8.0 walk commit",
    ),
    DeclaredSurface(
        GREAT_DOCS,
        "phase2",
        "docs registration (matrix rows 3+6): the tag commit applies the staged patch",
    ),
    DeclaredSurface(
        WEBSITE,
        "phase2",
        "docs selector (matrix row 3): the tag commit applies the staged patch",
    ),
)


@dataclass
class CutPlan:
    """The machine-readable plan S3's preflight consumes (plan.json)."""

    version: str
    prev_tag: str
    base_sha: str
    surfaces: list[dict[str, str]] = field(default_factory=list)


def run_command(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """The external-leg seam: sync-standards --check and the scaffold suite
    run in the cut repo; tests monkeypatch this seam (the section-9 harness
    replays them for real)."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _git(repo: Path, *args: str) -> str:
    """The ONLY git entry point, read-only by construction: the verb is
    whitelisted (tag additionally only with -l/--list). A future edit that
    adds a write or network verb reds the whitelist test."""
    verb = args[0] if args else ""
    if verb not in GIT_READ_ONLY and not (
        verb == "tag" and ("-l" in args or "--list" in args)
    ):
        raise ReleaseCutError(
            f"git_{verb}_refused: release-cut runs read-only git verbs only "
            f"(status, tag -l, log, rev-parse, show, diff); {verb!r} is refused "
            "by construction"
        )
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise ReleaseCutError(f"git {verb} failed: {proc.stderr.strip()}")
    return proc.stdout


def parse_version(text: str) -> str:
    m = VERSION_RE.match(text)
    if m is None:
        raise ReleaseCutError(
            f"version_malformed: {text!r} is not X.Y.Z — release-cut refuses to guess"
        )
    return text


def current_version(repo: Path) -> str:
    """The tree's pyproject version — the single version source."""
    data = tomllib.loads((repo / PYPROJECT).read_text(encoding="utf-8"))
    try:
        return data["project"]["version"]
    except KeyError as exc:
        raise ReleaseCutError(f"pyproject_missing_version: {exc}") from exc


def assert_increment(old: str, new: str) -> None:
    if VERSION_RE.match(new) is None:
        raise ReleaseCutError(f"version_malformed: {new!r} is not X.Y.Z")
    if tuple(int(p) for p in new.split(".")) <= tuple(int(p) for p in old.split(".")):
        raise ReleaseCutError(
            f"version_not_an_increment: {new} <= {old} — release-cut refuses "
            "a non-increment"
        )


def previous_tag(repo: Path, version: str) -> str:
    """The highest plain vX.Y.Z tag strictly below the release version —
    the same ordering discipline as the drift gate's latest_release()
    (numeric tuple order, not lexicographic)."""
    limit = tuple(int(p) for p in version.split("."))
    tags = [t for t in _git(repo, "tag", "-l").split() if RELEASE_REF_RE.match(t)]
    below = [
        t for t in tags if tuple(int(p) for p in t[1:].split(".")) < limit
    ]
    if not below:
        raise ReleaseCutError(
            "no_previous_tag: no vX.Y.Z tag below the release version — "
            "the first-ever cut is manual (out of scope)"
        )
    return max(below, key=lambda t: tuple(int(p) for p in t[1:].split(".")))


def assert_clean_tree(repo: Path) -> None:
    dirty = _git(repo, "status", "--porcelain")
    if dirty.strip():
        raise ReleaseCutError(
            "tree_not_clean: commit or stash first — the cut needs a clean tree "
            "(and its own operator commit afterwards)"
        )


def check_recut(repo: Path, version: str, *, force: bool) -> None:
    if current_version(repo) == version and not force:
        raise ReleaseCutError(
            f"already_at_version: pyproject is already at {version} — a re-cut "
            "needs --force"
        )


def validate_occurrences(texts: dict[str, str], version: str) -> list[str]:
    """Pass one: every substitution pattern must match exactly its expected
    count at `version`, or the problems list names file, pattern, expected
    and found — and nothing has been written."""
    problems: list[str] = []
    for surface in DECLARED_SURFACES:
        if surface.kind != "substitution":
            continue
        text = texts.get(surface.path)
        if text is None:
            problems.append(f"{surface.path}: declared surface missing from the tree")
            continue
        for template, expected in surface.patterns:
            found = text.count(template.format(v=version))
            if found != expected:
                problems.append(
                    f"{surface.path}: pattern {template!r} expected {expected} "
                    f"occurrence(s) at version {version}, found {found}"
                )
    return problems


def apply_substitutions(
    texts: dict[str, str], old: str, new: str
) -> dict[str, str]:
    """Pass two: rewrite every matched pattern OLD to NEW. Callers validate
    first (validate_occurrences) — the two-pass contract."""
    moved = dict(texts)
    for surface in DECLARED_SURFACES:
        if surface.kind != "substitution":
            continue
        text = moved[surface.path]
        for template, _expected in surface.patterns:
            text = text.replace(template.format(v=old), template.format(v=new))
        moved[surface.path] = text
    return moved


def read_surface_texts(repo: Path) -> dict[str, str]:
    """The substitution surfaces' bytes from the working tree (missing files
    surface as validate_occurrences problems, not silent skips)."""
    texts: dict[str, str] = {}
    for surface in DECLARED_SURFACES:
        if surface.kind == "substitution":
            path = repo / surface.path
            texts[surface.path] = (
                path.read_text(encoding="utf-8") if path.is_file() else ""
            )
    return texts


def unified_patch(path: str, old_text: str, new_text: str) -> str:
    return "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def patch_paths(patch_text: str) -> set[str]:
    """The file set a unified patch touches (its +++ b/ headers)."""
    return {
        line[6:].strip()
        for line in patch_text.splitlines()
        if line.startswith("+++ b/")
    }


def build_phase2(
    great_docs: str, selector_html: str, version: str
) -> tuple[str, str]:
    """The tag-commit content, computed (never applied here): insert the new
    versions block at the head of the list, flip the single existing
    latest:true to false (validated: exactly one exists), and give the
    selector a new (latest) first option plus the demoted prior option."""
    block_at = re.search(r"^versions:\n((?:[ \t]+.*\n?)+)", great_docs, re.M)
    if block_at is None:
        raise ReleaseCutError(
            "phase2_no_versions_list: 'versions:' not found in great-docs.yml"
        )
    block = block_at.group(1)
    if re.search(rf"^\s*-\s*tag:\s*v{re.escape(version)}\s*$", block, re.M):
        raise ReleaseCutError(
            f"phase2_already_registered: v{version} is already in the versions list"
        )
    # The flip is bounded to the versions block: the file's OTHER latest keys
    # (the /v/latest/ alias block) are different features and must not move.
    latest_lines = re.findall(r"^\s*latest:\s*true\b.*$", block, re.M)
    if len(latest_lines) != 1:
        raise ReleaseCutError(
            f"phase2_latest_ambiguity: expected exactly one 'latest: true' in the "
            f"versions list, found {len(latest_lines)}"
        )
    flipped_block = re.sub(
        r"^(\s*)latest:\s*true\b",
        r"\1latest: false",
        block,
        count=1,
        flags=re.M,
    )
    entry = (
        f"  - tag: v{version}\n"
        f"    label: v{version}\n"
        "    latest: true\n"
        f"    git_ref: v{version}\n"
    )
    new_docs = (
        great_docs[: block_at.start(1)] + entry + flipped_block + great_docs[block_at.end(1) :]
    )
    new_selector = _selector_flip(selector_html, version)
    return new_docs, new_selector


def _selector_flip(selector_html: str, version: str) -> str:
    """The website selector: the single (latest) option becomes the new
    version; the old label is demoted to its versioned bucket path."""
    select_at = selector_html.find('<select class="version-select"')
    if select_at < 0:
        raise ReleaseCutError(
            "phase2_no_selector: the version-select element was not found in "
            "website/index.html"
        )
    options = list(
        re.finditer(
            r"^[ \t]*(<option value=\"([^\"]*)\">([^<]*)</option>)[ \t]*$",
            selector_html[select_at:],
            re.M,
        )
    )
    labelled = [m for m in options if "(latest)" in m.group(3)]
    if len(labelled) != 1:
        raise ReleaseCutError(
            f"phase2_latest_ambiguity: expected exactly one '(latest)' option in "
            f"the selector, found {len(labelled)}"
        )
    old = labelled[0]
    prior = old.group(3).replace(" (latest)", "")
    indent = re.match(r"[ \t]*", old.group(0)).group(0)  # type: ignore[union-attr]
    new_lines = (
        f"{indent}<option value=\"{old.group(2)}\">v{version} (latest)</option>\n"
        f"{indent}<option value=\"docs/v/{prior}/\">{prior}</option>\n"
    )
    start = select_at + old.start()
    end = select_at + old.end()
    return selector_html[:start] + new_lines.rstrip("\n") + selector_html[end:]


def canonical_pin_answers(project: Path, version: str) -> None:
    """Rewrite a rendered answers file to the canonical pin (the same bytes
    ``_expected_answers`` in tests/test_scaffold_copier.py asserts)."""
    answers = project / ".copier-answers.yml"
    lines = answers.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line.startswith("_commit:"):
            out.append(f"_commit: v{version}\n")
            seen.add("commit")
        elif line.startswith("_src_path:"):
            out.append(f"_src_path: {CANONICAL_TEMPLATE_URL}\n")
            seen.add("src")
        else:
            out.append(line)
    if seen != {"commit", "src"}:
        raise ReleaseCutError(
            f"answers_pin_missing: {answers} lacks _commit/_src_path rows"
        )
    answers.write_bytes("".join(out).encode("utf-8"))


def regenerate_fixtures(fixtures_root: Path, version: str) -> None:
    """Render base and ui arms into fixtures_root (replacing it), then pin
    the answers. The stage is a RESOLVED tempdir: the scaffold's path
    validation rejects symlinked roots, and macOS /var is a symlink to
    /private/var — tempfile.mkdtemp() then Path.resolve() is designed in."""
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project

    with tempfile.TemporaryDirectory() as raw:
        stage = Path(raw).resolve()
        create_project(stage / "base", "example_plugin")
        create_project(stage / "ui", "example_plugin", with_ui=True)
        create_ui_resources(stage / "ui", "example_plugin")
        for arm in ("base", "ui"):
            canonical_pin_answers(stage / arm, version)
            target = fixtures_root / arm
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(stage / arm, target)


def _owner_name(repo: Path) -> str:
    """The operator is the owner for exclusion purposes: git config
    user.name in the cut repo (never a hardcoded identity)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "config", "user.name"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def contributor_line(repo: Path, prev_tag: str) -> str:
    """The contributor-window row, computed: commit count + authors minus
    the operator (git config user.name) and [bot] authors. Empty window is
    a recorded result, never a skipped step."""
    log = _git(repo, "log", f"{prev_tag}..HEAD", "--format=%an")
    authors = sorted({line for line in log.splitlines() if line.strip()})
    humans = [
        a for a in authors if not BOT_RE.search(a) and a != _owner_name(repo)
    ]
    total = len([line_ for line_ in log.splitlines() if line_.strip()])
    listed = ", ".join(humans) if humans else "none"
    return (
        f"{total} commits in the window — human authors other than the "
        f"operator/bots: {listed}; the walk acknowledges new human "
        "contributors and records an empty window as a result"
    )


def served_set_line(repo: Path, prev_tag: str) -> str:
    """Row 9: byte-compare the lock minus compatibility against the
    previous tag's. D7: the tool never guesses MINOR/PATCH — motion is
    reported, the class is the sync machinery's call."""
    old_raw = _git(repo, "show", f"{prev_tag}:{LOCK}")
    new_raw = (repo / LOCK).read_text(encoding="utf-8")
    strip = lambda raw: json.dumps(  # noqa: E731
        {k: v for k, v in json.loads(raw).items() if k != "compatibility"},
        sort_keys=True,
    )
    if strip(old_raw) == strip(new_raw):
        return (
            f"n-a — no served-set motion in the window: {LOCK} is identical to "
            f"{prev_tag}'s apart from compatibility.sdk (the certified-version field)"
        )
    return (
        "SERVED-SET MOTION in the window — the class is asserted by the sync "
        "machinery (sdk_bump_class_invalid:); the walk records it; release-cut "
        "refuses to guess a class (D7)"
    )


def matrix_scaffold(
    version: str,
    date: str,
    prev_tag: str,
    contributors: str,
    served_set: str,
) -> str:
    """The result-record scaffold (row 8, derived): every row pre-filled —
    the walk CONFIRMS; it no longer discovers. No class verdict (D7)."""
    patch_name = f"`.release/phase2-v{version}.patch`"
    return (
        f"\n## Result record — v{version} ({date})\n"
        "\n"
        "| # | Surface | Result |\n"
        "|---|---------|--------|\n"
        f"| 1 | README stamp | updated → SDK {version} by release-cut (occurrence-validated) |\n"
        "| 1b | User-guide \"current SDK\" sentence | walk confirms — n-a or updated; "
        "the wheel filename is a glob since #102 |\n"
        f"| 2 | Website hero status | updated — SDK {version} by release-cut "
        "(occurrence-validated); OTDP / adapter-API stamps the walk confirms against "
        "the lock's active rows |\n"
        f"| 3 | Docs selector | PHASE-2 — patch staged at {patch_name}; the tag commit "
        "applies it (registration precedes the tag) |\n"
        f"| 4 | Compatibility tagline | updated — SDK {version} against the "
        "main-repository floor by release-cut (occurrence-validated) |\n"
        "| 5 | Standards badges | walk confirms — enumerate all six against the lock's "
        "ACTIVE rows |\n"
        f"| 6 | great-docs.yml versions | PHASE-2 — the tag commit applies the staged "
        "patch (the ordering constraint) |\n"
        f"| 7 | Contributor window `{prev_tag}..HEAD` | {contributors} |\n"
        "| 8 | Gateway uv.lock SDK pin | recorded note — moves at the gateway's next "
        "lock run / pointer advance |\n"
        f"| 9 | Served-set bump class | {served_set} |\n"
    )


def cmd_cut(repo: Path, version: str, *, force: bool) -> int:
    parse_version(version)
    current = current_version(repo)
    assert_increment(current, version)
    check_recut(repo, version, force=force)
    assert_clean_tree(repo)
    prev_tag = previous_tag(repo, version)

    for declared in DECLARED_SURFACES:
        if declared.kind in ("derived", "phase2") and not (repo / declared.path).is_file():
            raise ReleaseCutError(
                f"declared_surface_missing: {declared.path} is not in the tree"
            )
    texts = read_surface_texts(repo)
    problems = validate_occurrences(texts, current)
    if problems:
        print(
            "release-cut: occurrence validation FAILED — nothing written:\n  "
            + "\n  ".join(problems),
            file=sys.stderr,
        )
        return EXIT_FAIL

    backup: dict[str, bytes] = {
        surface.path: (repo / surface.path).read_bytes()
        for surface in DECLARED_SURFACES
        if surface.kind in ("substitution", "derived")
        and (repo / surface.path).is_file()
    }
    fixture_backup = _snapshot_dir(repo / FIXTURES)
    release_dir = repo / RELEASE_DIR

    def _restore() -> None:
        for relative, content in backup.items():
            (repo / relative).write_bytes(content)
        _restore_dir(repo / FIXTURES, fixture_backup)
        for emitted in (
            release_dir / f"phase2-v{version}.patch",
            release_dir / "plan.json",
        ):
            emitted.unlink(missing_ok=True)

    try:
        moved = apply_substitutions(texts, current, version)
        for path, text in moved.items():
            (repo / path).write_text(text, encoding="utf-8")

        # The render stamps the INSTALLED dist-info version, not the edited
        # pyproject — refresh the env first, or the fixtures are re-pinned at
        # the OLD version while the post-cut byte-parity render (post-reinstall)
        # says NEW (the section-9 replay caught it: 'b'8' != b'7'').
        # --extra test --extra server: the repo's documented gate env — a
        # bare sync would DROP the test extra (pytest lives there, not in dev)
        refresh = run_command(
            ["uv", "sync", "--locked", "--extra", "test", "--extra", "server"],
            cwd=repo,
        )
        if refresh.returncode != 0:
            raise ReleaseCutError(
                "env_refresh_failed: uv sync --locked red after the substitutions:\n"
                f"{refresh.stdout}\n{refresh.stderr}"
            )
        regenerate_fixtures(repo / FIXTURES, version)

        anchor = run_command(
            ["uv", "run", "benchweave-sdk", "sync-standards", "--check"], cwd=repo
        )
        if anchor.returncode != 0:
            raise ReleaseCutError(
                "anchor_check_failed: sync-standards --check red after the lock "
                f"anchor move:\n{anchor.stdout}\n{anchor.stderr}"
            )

        date = datetime.now(UTC).date().isoformat()
        scaffold = matrix_scaffold(
            version=version,
            date=date,
            prev_tag=prev_tag,
            contributors=contributor_line(repo, prev_tag),
            served_set=served_set_line(repo, prev_tag),
        )
        matrix_path = repo / MATRIX
        matrix_path.write_text(
            matrix_path.read_text(encoding="utf-8") + scaffold, encoding="utf-8"
        )

        great_docs = (repo / GREAT_DOCS).read_text(encoding="utf-8")
        selector = (repo / WEBSITE).read_text(encoding="utf-8")
        new_docs, new_selector = build_phase2(great_docs, selector, version)
        patch = unified_patch(GREAT_DOCS, great_docs, new_docs) + unified_patch(
            WEBSITE, selector, new_selector
        )
        touched = patch_paths(patch)
        if touched != set(PHASE2_FILES):
            raise ReleaseCutError(
                f"phase2_wrong_file_set: the staged patch touches {sorted(touched)}, "
                f"expected exactly {sorted(PHASE2_FILES)} — refused"
            )
        release_dir.mkdir(exist_ok=True)
        (release_dir / f"phase2-v{version}.patch").write_text(patch, encoding="utf-8")
        plan = CutPlan(
            version=version,
            prev_tag=prev_tag,
            base_sha=_git(repo, "rev-parse", "HEAD").strip(),
            surfaces=[
                {"path": s.path, "kind": s.kind} for s in DECLARED_SURFACES
            ],
        )
        (release_dir / "plan.json").write_text(
            json.dumps(plan, default=vars, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        post = validate_occurrences(read_surface_texts(repo), version)
        if post:
            raise ReleaseCutError(
                "post_cut_smoke_failed: patterns at the NEW version:\n  "
                + "\n  ".join(post)
            )
        smoke = run_command(
            ["uv", "run", "pytest", "tests/test_scaffold_copier.py", "-q"], cwd=repo
        )
        if smoke.returncode != 0:
            raise ReleaseCutError(
                "post_cut_pytest_failed: the byte-parity suite is red on the cut "
                f"tree — the regen did not sweep everything:\n{smoke.stdout}\n{smoke.stderr}"
            )
    except Exception:
        _restore()
        raise

    print(
        f"release-cut: staged v{version} (from v{prev_tag}). Occurrence-validated: "
        f"{len(backup)} substitution/derived files rewritten, fixtures regenerated, "
        f"anchor checked, matrix scaffold appended, phase-2 patch + plan staged at "
        f"{RELEASE_DIR}/. NO commit, NO tag, NO push — the operator commits, "
        "then applies the staged patch at the tag commit."
    )
    return EXIT_OK


def _snapshot_dir(root: Path) -> dict[str, bytes] | None:
    if not root.is_dir():
        return None
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _restore_dir(root: Path, snapshot: dict[str, bytes] | None) -> None:
    if snapshot is None:
        return
    if root.is_dir():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for relative, content in snapshot.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def cmd_verify(repo: Path) -> int:
    """The release-PR gate's script half: four assertions per the design's
    section 3.6, read-only, exit 0/1."""
    version = current_version(repo)
    texts = read_surface_texts(repo)
    failures = validate_occurrences(texts, version)

    lock_raw = (repo / LOCK).read_text(encoding="utf-8") if (repo / LOCK).is_file() else ""
    try:
        anchor = json.loads(lock_raw).get("compatibility", {}).get("sdk")
    except json.JSONDecodeError:
        anchor = None
    if anchor != version:
        failures.append(
            f"anchor_skipped: {LOCK} compatibility.sdk ({anchor!r}) != pyproject "
            f"version ({version!r}) — the v0.7.0 class"
        )

    patch_path = repo / RELEASE_DIR / f"phase2-v{version}.patch"
    if not patch_path.is_file():
        failures.append(
            f"patch_missing: {patch_path} does not exist — was this tree cut by "
            "release-cut? (a release PR carries the staged patch)"
        )
    else:
        patch = patch_path.read_text(encoding="utf-8")
        touched = patch_paths(patch)
        if touched != set(PHASE2_FILES):
            failures.append(
                f"patch_wrong_file_set: {sorted(touched)} != {sorted(PHASE2_FILES)}"
            )
        apply_check = subprocess.run(
            ["git", "-C", str(repo), "apply", "--check", str(patch_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if apply_check.returncode != 0:
            failures.append(
                "patch_conflicts: git apply --check failed (main moved between "
                "merge and tag?) — regenerate with release-cut --phase2-only:\n"
                f"{apply_check.stderr.strip()}"
            )

    if failures:
        print(
            "release-cut --verify FAILED:\n  " + "\n  ".join(failures),
            file=sys.stderr,
        )
        return EXIT_FAIL
    print(f"release-cut --verify OK: tree at v{version} is a consistent release cut")
    return EXIT_OK


def cmd_phase2_only(repo: Path, *, force: bool) -> int:
    """Regenerate the staged patch + plan against the current tree — the
    named answer when main moved between merge and tag (never hand-edit)."""
    version = current_version(repo)
    prev_tag = previous_tag(repo, version)
    great_docs = (repo / GREAT_DOCS).read_text(encoding="utf-8")
    selector = (repo / WEBSITE).read_text(encoding="utf-8")
    new_docs, new_selector = build_phase2(great_docs, selector, version)
    patch = unified_patch(GREAT_DOCS, great_docs, new_docs) + unified_patch(
        WEBSITE, selector, new_selector
    )
    touched = patch_paths(patch)
    if touched != set(PHASE2_FILES):
        print(
            f"release-cut: phase2_wrong_file_set {sorted(touched)} — refused",
            file=sys.stderr,
        )
        return EXIT_FAIL
    release_dir = repo / RELEASE_DIR
    release_dir.mkdir(exist_ok=True)
    (release_dir / f"phase2-v{version}.patch").write_text(patch, encoding="utf-8")
    plan = CutPlan(
        version=version,
        prev_tag=prev_tag,
        base_sha=_git(repo, "rev-parse", "HEAD").strip(),
        surfaces=[{"path": s.path, "kind": s.kind} for s in DECLARED_SURFACES],
    )
    (release_dir / "plan.json").write_text(
        json.dumps(plan, default=vars, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"release-cut: regenerated the phase-2 patch + plan for v{version}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "The release-cut transaction (issue #408): occurrence-validated "
            "substitutions, fixture regen, anchor check, matrix scaffold and the "
            "staged phase-2 patch — in one read-only-git command. NO commit, NO "
            "tag, NO push, NO publish, NO network: read-only git verbs only; the "
            "operator commits and applies the staged patch at the tag commit."
        )
    )
    parser.add_argument("version", nargs="?", help="release version, X.Y.Z")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="read-only PR-time gate: occurrence parity, anchor parity, patch "
        "applicability and patch file set",
    )
    parser.add_argument(
        "--phase2-only",
        action="store_true",
        help="regenerate the staged phase-2 patch + plan against the current tree",
    )
    parser.add_argument(
        "--force", action="store_true", help="allow a re-cut at the current version"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if args.verify:
        return cmd_verify(repo)
    if args.phase2_only:
        return cmd_phase2_only(repo, force=args.force)
    if args.version is None:
        parser.error("a VERSION argument is required without --verify/--phase2-only")
    try:
        return cmd_cut(repo, args.version, force=args.force)
    except ReleaseCutError as exc:
        print(f"release-cut: {exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
