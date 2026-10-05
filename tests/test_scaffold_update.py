"""R-4 — the update promise, per-push lane (issue #347 WS2, design §6).

Protocol: scaffold a project from the repository's template history at its
newest template-touching ancestor (BASE), apply ``new``'s answers-pin
discipline against a throwaway tagged template repository, author-edit three
owned files, commit, then ``copier.run_update`` to the current template and
assert A1-A5:

- A1 managed: ``AI-GUIDE.md`` byte-equal to the current template's render
  (equality, not "changed" — a no-delta push still asserts meaningfully).
- A2 owned: every author-edited owned file byte-identical to the author
  state. Semantics (corrected after a confounded first experiment — the
  record's §1 row was RIGHT): ``_skip_if_exists`` IS honored at update
  time for paths that match — exact names and globstar patterns protect
  the file entirely (author bytes preserved; template seed changes reach
  new projects only, which is the §2.2 intent). A single ``*`` does NOT
  cross ``/`` in update-time matching, so the shipped list uses
  ``src/**``/``tests/**`` (pinned by test_skip_list_is_load_bearing_on_update).
  Files matching NO pattern (the managed AI-GUIDE, and anything a future
  list edit misses) ride the 3-way merge: same-line divergence produces
  conflict markers with both sides intact (the wrong-base test below pins
  that nothing is silently lost).
- A3 provenance: answers ``_commit`` == the target ref; ``_src_path``
  preserved by the update.
- A4 health: ``benchweave-sdk check`` exits 0 on the updated descriptor.
- A5 no strays: the git status set is exactly the update's own footprint;
  no conflict markers anywhere; the file set only grows by template-added
  files.

Lane note (disclosed deviation from the record's §6 wording): BASE is the
newest ancestor whose tree touches ``template/`` — literal ``HEAD~1`` has no
template at the landing push — and the update runs offline against a
throwaway tagged repository synthesized from the real history's two template
states, because copier requires dunamai-resolvable versions (tags) on both
sides and the branch's own commits are untagged. The release lane (real
``v{version}`` tags against the canonical GitHub URL) rides the publish
flow per the design's CI-cost note.

Git plumbing uses ``subprocess`` (git has no in-process API in this
dependency set; copier itself shells out to git the same way). The
production code adds no shell-outs — the keyword-scan deviation is this
test module only.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from benchweave_sdk import __version__
from benchweave_sdk.cli import main as cli_main
from benchweave_sdk.presentation import create_ui_resources
from benchweave_sdk.scaffold import _enforce_lf, _repo_template_members  # noqa: PLC2701
from benchweave_sdk.served import active_version

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "scaffold_expected"
PACKAGE = "example_plugin"
AUTHOR_LINE = "AUTHOR NOTE: my device-specific line\n"
BASE_TAG = "v0.9.0"
TARGET_TAG = "v0.9.1"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Pin LF: the repo contract is LF everywhere, but on Windows author edits
    # and copier writes can be CRLF. autocrlf=input normalizes CRLF→LF at add
    # time, so the index is LF and `git status` reads owned files as unmodified
    # after _enforce_lf renormalizes the working tree.
    return subprocess.run(
        ["git", "-c", "core.autocrlf=input", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    )


def _git_out(cwd: Path, *args: str) -> str:
    return _git(cwd, *args).stdout.strip()


def _git_init(cwd: Path) -> None:
    """git init with the harness's line-ending contract pinned (PR #93).

    core.autocrlf=input commits CRLF working bytes as LF and never
    converts on checkout; core.eol=lf keeps checkouts LF. Windows
    text-mode writes (CRLF bytes) then commit as LF, and _enforce_lf's
    normalization leaves git status clean instead of reporting every
    author-edited file as modified.
    """
    _git(cwd, "init", "-q")
    _git(cwd, "config", "core.autocrlf", "input")
    _git(cwd, "config", "core.eol", "lf")


def _tree(root: Path) -> dict[str, bytes]:
    """Working-tree files only — ``.git`` internals (the index the update
    rewrites) are not project content."""
    return {
        entry.relative_to(root).as_posix(): entry.read_bytes().replace(b"\r\n", b"\n")
        for entry in sorted(root.rglob("*"))
        if entry.is_file() and ".git" not in entry.relative_to(root).parts
    }


def _write_tree(root: Path, members: dict[str, bytes]) -> None:
    """Write template members under ``root`` (copier.yml + template/**).

    Only the template content is wiped — the throwaway repos this writes
    into carry a freshly initialized ``.git`` that must survive the second
    (target-state) write.
    """
    root.mkdir(parents=True, exist_ok=True)
    for stale in (root / "template", root / "copier.yml"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
    for relative, content in members.items():
        member = root / relative
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(content)


def _base_members(tmp: Path) -> dict[str, bytes] | None:
    """The repository's template at its newest template-touching ancestor."""
    if shutil.which("git") is None:
        pytest.skip("git unavailable — the R-4 lane is held, not passed")
    history = _git_out(REPO, "rev-list", "-n", "1", "HEAD", "--", "template/", "copier.yml")
    if not history:
        pytest.skip("no template history in this checkout — the R-4 lane is held, not passed")
    archive = subprocess.run(
        ["git", "-C", str(REPO), "archive", history, "--", "template/", "copier.yml"],
        capture_output=True,
        check=True,
    ).stdout
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for entry in tar.getmembers():
            if entry.isfile():
                extracted = tar.extractfile(entry)
                assert extracted is not None
                members[entry.name] = extracted.read()
    return members


def _pin_local_answers(project: Path, src: Path, commit: str) -> None:
    """``new``'s pin discipline, pointed at the throwaway repo instead of the
    canonical URL + release tag (the push lane's offline equivalent)."""
    answers = project / ".copier-answers.yml"
    rendered = answers.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in rendered if not line.startswith(("_commit:", "_src_path:"))]
    kept[1:1] = [f"_commit: {commit}\n", f"_src_path: {src}\n"]
    answers.write_bytes("".join(kept).encode("utf-8"))


def _build_tagged_template_repo(
    tmp: Path, base: dict[str, bytes], target: dict[str, bytes]
) -> Path:
    repo = tmp / "template-repo"
    repo.mkdir()
    _git_init(repo)
    _write_tree(repo, base)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=r4@benchweave", "-c", "user.name=r4", "commit", "-qm", "base")
    _git(repo, "tag", BASE_TAG)
    _write_tree(repo, target)
    _git(repo, "add", "-A")
    # --allow-empty: a no-delta push (BASE content == target content) still
    # needs the tagged target commit for dunamai's version resolution.
    _git(repo, "-c", "user.email=r4@benchweave", "-c", "user.name=r4", "commit",
         "--allow-empty", "-qm", "target")
    _git(repo, "tag", TARGET_TAG)
    return repo


@pytest.fixture()
def update_stage(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes], dict[str, bytes]]:
    base = _base_members(tmp_path)
    target = _repo_template_members()
    assert base is not None and target is not None
    repo = _build_tagged_template_repo(tmp_path, base, target)
    # The `new`-shaped render source: a NON-GIT materialized copy of BASE —
    # the same shape create_project renders from, so the answers arrive
    # unpinned and the test applies the pin itself.
    materialized = tmp_path / "materialized-base"
    _write_tree(materialized, base)
    return repo, materialized, base, target


def _scaffold(stage: tuple, project: Path, with_ui: bool) -> None:
    from copier import run_copy

    repo, materialized, _base, _target = stage
    run_copy(
        str(materialized),
        str(project),
        data={
            "package_name": PACKAGE,
            "with_ui": with_ui,
            "sdk_version": __version__,
            "otdp_version": active_version("otdp"),
        },
        defaults=True,
        quiet=True,
    )
    _enforce_lf(project)
    base_sha = _git_out(repo, "rev-parse", BASE_TAG)
    _pin_local_answers(project, repo, base_sha)
    if with_ui:
        create_ui_resources(project, PACKAGE)


@pytest.mark.parametrize("with_ui", [False, True], ids=["base", "ui"])
def test_update_keeps_the_update_promise(
    tmp_path: Path, update_stage: tuple, with_ui: bool
) -> None:
    repo, _materialized, base, target = update_stage
    project = tmp_path / ("P-ui" if with_ui else "P")
    _scaffold(update_stage, project, with_ui)

    # Author edits three owned files (the record's protocol) — README,
    # CLAUDE.md and the adapter seed — then commits.
    for relative in ("README.md", "CLAUDE.md", f"src/{PACKAGE}/adapter.py"):
        path = project / relative
        path.write_bytes(path.read_bytes() + AUTHOR_LINE.encode())
    _git_init(project)
    _git(project, "add", "-A")
    _git(project, "-c", "user.email=author@benchweave", "-c", "user.name=author",
         "commit", "-qm", "author state")
    author_state = _tree(project)

    # Owned seeds the template changed between BASE and target: these merge
    # on update (3-way), everything else must come through byte-identical.
    # copier.yml is template CONFIG, never a rendered member — a config-only
    # delta touches nothing in the project.
    changed = sorted(
        # Project-relative paths (the .jinja suffix is template-side only):
        # this set is compared against project file names in A2/A5 below.
        # WS3 fold: the suffix mismatch was masked in WS2 — every member its
        # tests mutated was .jinja-less, and a clean checkout's delta set is
        # empty — but any .jinja-bearing template delta (the skills, the
        # answers template) made `changed` name paths that never exist in
        # the project, so the A2 carve-out and the A5 footprint both went
        # blind for exactly those files.
        relative.removeprefix("template/").removesuffix(".jinja")
        for relative in set(base) | set(target)
        if relative.startswith("template/") and base.get(relative) != target.get(relative)
    )

    from copier import run_update

    run_update(str(project), defaults=True, vcs_ref=TARGET_TAG, overwrite=True, quiet=True)
    _enforce_lf(project)
    updated = _tree(project)

    # A1 managed: byte-equal to the current template render.
    # The managed guide renders from template/AI-GUIDE.md.jinja (issue
    # #394 made it template-side), so the expected bytes are the pinned
    # fixture's render, per arm — the same authority managed_assets use.
    assert updated["AI-GUIDE.md"] == (
        FIXTURES / ("ui" if with_ui else "base") / "AI-GUIDE.md"
    ).read_bytes()

    # A1 extension (WS3 R-5d): the managed agent assets ride the same
    # byte-exactness — the update renders them exactly as `new` renders
    # them, version stamps included. The fixture is that render, pinned by
    # R-2; the set is derived from the template members (never a second
    # list to go stale), so every managed asset the target carries is
    # checked and template growth lands here automatically.
    managed_assets = sorted(
        member.removeprefix("template/").removesuffix(".jinja")
        for member in target
        if member == "template/AGENTS.md.jinja" or member.startswith("template/.claude/")
    )
    assert managed_assets, "the template must carry the managed agent assets"
    for relative in managed_assets:
        assert updated[relative] == (
            FIXTURES / ("ui" if with_ui else "base") / relative
        ).read_bytes(), relative

    # A2 owned: the author's three files plus every owned file whose seed
    # the template did NOT change survive byte-identically; a skip-protected
    # file whose seed DID change survives byte-identically TOO (skip-wins —
    # pinned live by test_upgrade_moves_managed_state_and_preserves_author
    # and test_skip_list_is_load_bearing_on_update; the adversary fold B-F2
    # corrected this arm, which previously asserted merge markers for
    # changed seeds — inverted against the shipped semantics).
    for relative in ("README.md", "CLAUDE.md", f"src/{PACKAGE}/adapter.py"):
        assert updated[relative] == author_state[relative], relative
    for relative, content in author_state.items():
        if relative == ".copier-answers.yml":
            continue
        if relative in changed and (relative == "AI-GUIDE.md" or relative in managed_assets):
            continue  # managed files ride the 3-way merge when the template moves them
        assert updated[relative] == content, relative

    # A3 provenance: the answers' _commit advanced to the target ref and the
    # pinned _src_path was preserved by the update.
    answers = dict(
        line.split(":", 1) for line in updated[".copier-answers.yml"].decode().splitlines()[1:]
    )
    assert answers["_commit"].strip() == TARGET_TAG
    assert answers["_src_path"].strip() == str(repo)

    # A4 health: the updated project's descriptor still checks clean.
    assert cli_main(["check", str(project / "src" / PACKAGE / "descriptor.json")]) == 0

    # A5 no strays: the update's git footprint is exactly the changed files
    # plus the answers file; no markers anywhere else; the file set only
    # grows by template-added files. (Raw porcelain: an unstaged ' M' line's
    # leading space is significant — stripping it would shift the path slice.)
    porcelain = _git(project, "status", "--porcelain").stdout.splitlines()
    touched = {line[3:] for line in porcelain}
    expected_touched = {".copier-answers.yml"} | set(changed)
    assert touched == expected_touched, porcelain
    added_by_template = {
        relative.removeprefix("template/") for relative in set(target) - set(base)
    }
    assert set(updated) - set(author_state) <= added_by_template
    for relative, content in updated.items():
        if relative not in changed:
            assert b"<<<<<<<" not in content, relative


def test_update_without_the_answers_pin_cannot_resolve_base(tmp_path: Path) -> None:
    """The record's RED control (ii), as a standing pin: ``new`` renders from
    a non-git materialized copy, so an unpinned answers file names an
    ephemeral directory and carries no ``_commit`` — update cannot resolve
    the 3-way base and refuses loudly."""
    from copier import run_copy, run_update

    base = _base_members(tmp_path)
    assert base is not None
    materialized = tmp_path / "materialized-base"
    _write_tree(materialized, base)
    project = tmp_path / "P-unpinned"
    run_copy(
        str(materialized),
        str(project),
        data={
            "package_name": PACKAGE,
            "with_ui": False,
            "sdk_version": __version__,
            "otdp_version": active_version("otdp"),
        },
        defaults=True,
        quiet=True,
    )
    _enforce_lf(project)
    assert "_commit:" not in (project / ".copier-answers.yml").read_text(encoding="utf-8")
    _git_init(project)
    _git(project, "add", "-A")
    _git(project, "-c", "user.email=author@benchweave", "-c", "user.name=author",
         "commit", "-qm", "author state")
    from copier.errors import UserMessageError

    with pytest.raises(UserMessageError, match="cannot obtain old template references"):
        run_update(str(project), defaults=True, vcs_ref=TARGET_TAG, overwrite=True, quiet=True)


def test_wrong_base_provenance_never_silently_loses_author_bytes(tmp_path: Path) -> None:
    """A2's teeth via the merge lane (AI-GUIDE matches no skip pattern, so
    it rides the 3-way merge): when the pinned base names template state
    whose content differs from what the author actually has, the update
    mis-attributes the delta and the author's lines survive only inside
    conflict markers. Wrong provenance is loud, never silent."""
    from copier import run_copy, run_update

    base = _base_members(tmp_path)
    assert base is not None
    target = _repo_template_members()
    assert target is not None
    # A third state A0: the base with a DIFFERENT AI-GUIDE first line, so the
    # pinned base cannot explain the project's AI-GUIDE bytes.
    a0 = dict(base)
    a0["template/AI-GUIDE.md.jinja"] = base["template/AI-GUIDE.md.jinja"].replace(
        b"# Build a BenchWeave device plugin with AI", b"# A0 lineage guide"
    )
    repo = tmp_path / "template-repo-a0"
    repo.mkdir()
    _git_init(repo)
    _write_tree(repo, a0)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=r4@benchweave", "-c", "user.name=r4", "commit", "-qm", "a0")
    _git(repo, "tag", "v0.8.0")
    _write_tree(repo, target)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=r4@benchweave", "-c", "user.name=r4", "commit", "-qm", "target")
    _git(repo, "tag", TARGET_TAG)

    materialized = tmp_path / "materialized-a0"
    _write_tree(materialized, a0)
    project = tmp_path / "P-wrongbase"
    run_copy(
        str(materialized),
        str(project),
        data={
            "package_name": PACKAGE,
            "with_ui": False,
            "sdk_version": __version__,
            "otdp_version": active_version("otdp"),
        },
        defaults=True,
        quiet=True,
    )
    _enforce_lf(project)
    _pin_local_answers(project, repo, _git_out(repo, "rev-parse", "v0.8.0"))
    # The author's real lineage is the BASE guide, locally edited on the same
    # first line — all three states disagree there.
    guide = project / "AI-GUIDE.md"
    guide.write_bytes(
        base["template/AI-GUIDE.md.jinja"].replace(
            b"# Build a BenchWeave device plugin with AI", b"# AUTHOR-localised guide"
        )
    )
    _git_init(project)
    _git(project, "add", "-A")
    _git(project, "-c", "user.email=author@benchweave", "-c", "user.name=author",
         "commit", "-qm", "author state")
    run_update(str(project), defaults=True, vcs_ref=TARGET_TAG, overwrite=True, quiet=True)
    _enforce_lf(project)
    text = guide.read_text(encoding="utf-8")
    assert "<<<<<<< before updating" in text
    assert "AUTHOR-localised guide" in text, "the author's line must survive the wrong-base merge"
    assert "A0 lineage guide" in text or "device plugin with AI" in text


# --- upgrade / adopt: the WS2 commands (record sections 2.4-2.5) -------------


def _upgrade_stage(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    """A tagged throwaway repo whose TARGET deliberately moves the managed
    AI-GUIDE and one owned seed, so the upgrade visibly moves bytes."""
    base = _base_members(tmp_path)
    assert base is not None
    target = dict(_repo_template_members() or {})
    assert target
    # Deltas on three vehicles: the managed AI-GUIDE (never in the skip
    # list — it must MOVE), the exact-name owned README, and the src/**
    # owned adapter seed.
    target["template/AI-GUIDE.md.jinja"] = target["template/AI-GUIDE.md.jinja"].replace(
        b"# Build a BenchWeave device plugin with AI",
        b"# Build a BenchWeave device plugin with AI v2",
    )
    target["template/README.md"] = base["template/README.md"].replace(
        b"# Device plugin starter", b"# Device plugin starter v2"
    )
    adapter_key = "template/src/{{ package_name }}/adapter.py.jinja"
    target[adapter_key] = target[adapter_key].replace(
        b"def create_plugin():", b"def create_plugin_v2():"
    )
    repo = _build_tagged_template_repo(tmp_path, base, target)
    materialized = tmp_path / "materialized-upg-base"
    _write_tree(materialized, base)
    return repo, materialized, target


def _scaffold_offline(
    materialized: Path, repo: Path, project: Path, with_ui: bool = False
) -> None:
    from copier import run_copy

    run_copy(
        str(materialized),
        str(project),
        data={
            "package_name": PACKAGE,
            "with_ui": with_ui,
            "sdk_version": __version__,
            "otdp_version": active_version("otdp"),
        },
        defaults=True,
        quiet=True,
    )
    _enforce_lf(project)
    _pin_local_answers(project, repo, _git_out(repo, "rev-parse", BASE_TAG))


def _author_commit(project: Path) -> None:
    _git_init(project)
    _git(project, "add", "-A")
    _git(project, "-c", "user.email=author@benchweave", "-c", "user.name=author",
         "commit", "-qm", "author state")


def test_upgrade_moves_managed_state_and_preserves_author(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold_update import upgrade_project

    repo, materialized, _target = _upgrade_stage(tmp_path)
    project = tmp_path / "P-upgrade"
    _scaffold_offline(materialized, repo, project)
    # The author diverges on the same lines the template moved.
    readme = project / "README.md"
    readme.write_bytes(
        readme.read_bytes().replace(b"# Device plugin starter", b"# AUTHOR plugin")
    )
    adapter = project / "src" / PACKAGE / "adapter.py"
    adapter.write_bytes(
        adapter.read_bytes().replace(
            b"def create_plugin():", b"def create_plugin_author():"
        )
    )
    guide = project / "AI-GUIDE.md"
    guide.write_bytes(
        guide.read_bytes().replace(
            b"# Build a BenchWeave device plugin with AI",
            b"# AUTHOR-localised guide",
        )
    )
    author_state = _tree(project)
    _author_commit(project)
    conflicted, _restored = upgrade_project(project, target_ref=TARGET_TAG)
    # A1 managed: AI-GUIDE rides the 3-way merge; the author edited it too,
    # so it conflicts loudly (both sides intact) and is reported.
    assert conflicted == ["AI-GUIDE.md"]
    guide_text = guide.read_text(encoding="utf-8")
    assert "<<<<<<< before updating" in guide_text
    assert "AUTHOR-localised guide" in guide_text and "with AI v2" in guide_text
    # A2 owned: exact-name and src/** skip members stay byte-identical to
    # the author state — the template deltas do NOT land over them.
    assert (project / "README.md").read_bytes() == author_state["README.md"]
    assert adapter.read_bytes() == author_state[f"src/{PACKAGE}/adapter.py"]
    # A3 provenance advanced to the target ref.
    answers = (project / ".copier-answers.yml").read_text(encoding="utf-8")
    assert f"_commit: {TARGET_TAG}" in answers


def test_upgrade_conflicts_loudly_on_an_author_edited_managed_skill(tmp_path: Path) -> None:
    """R-5d live RED (WS3 design §4): author-edit a MANAGED skill, then
    upgrade past a template that moves the same lines. The conflict path
    fires — markers with both sides intact, the path reported — never a
    silent clobber back to template bytes. (A weak form that only asserts
    equality with the template render would pass under clobber; the
    survival assertions are the teeth.)"""
    from benchweave_sdk.scaffold_update import upgrade_project

    base = dict(_repo_template_members() or {})
    assert base
    skill_member = "template/.claude/skills/benchweave-descriptor/SKILL.md.jinja"
    assert skill_member in base, "the template must carry the managed skill"
    target = dict(base)
    target[skill_member] = base[skill_member].replace(
        b"# Descriptor authoring", b"# Descriptor authoring (template moved)"
    )
    repo = _build_tagged_template_repo(tmp_path, base, target)
    materialized = tmp_path / "materialized-skill"
    _write_tree(materialized, base)
    project = tmp_path / "P-skill-conflict"
    _scaffold_offline(materialized, repo, project)
    skill = project / ".claude" / "skills" / "benchweave-descriptor" / "SKILL.md"
    skill.write_bytes(
        skill.read_bytes().replace(b"# Descriptor authoring", b"# AUTHOR-tuned skill")
    )
    _author_commit(project)
    conflicted, restored = upgrade_project(project, target_ref=TARGET_TAG)
    assert restored == []
    assert conflicted == [".claude/skills/benchweave-descriptor/SKILL.md"]
    text = skill.read_text(encoding="utf-8")
    assert "<<<<<<< before updating" in text
    assert "AUTHOR-tuned skill" in text, "the author's edit must survive"
    assert "(template moved)" in text, "the template's edit must survive too"


def test_upgrade_renders_managed_assets_with_the_installed_stamp(tmp_path: Path) -> None:
    """R-5d's production promise on the ``upgrade_project`` lane, aged BYTES
    edition (adversary fold B-F1): a project rendered at an OLD SDK version
    — managed bytes AND answers both carrying the old stamp — upgrades to
    the installed SDK and every managed asset re-stamps to the INSTALLED
    version. The ``data`` override in ``upgrade_project`` is the mechanism:
    a raw ``run_update`` takes its render context from the stored answers,
    so without the override the aged stamp simply stays (measured: the
    template's content moves, the stamp does not). Aging only the answers
    is NOT enough — the project bytes then disagree with the old render and
    the 3-way merge preserves them as author edits, keeping the test green
    with the guard deleted. The bytes must age too. WS2 could not pin any
    of this (its only managed file, AI-GUIDE, carried no version token)."""
    from copier import run_copy

    from benchweave_sdk.scaffold_update import upgrade_project

    old = "0.0.1-old"
    base = dict(_repo_template_members() or {})
    assert base
    # No template delta beyond the tag: the only moving bytes are the version
    # stamps, which is exactly what this test isolates.
    repo = _build_tagged_template_repo(tmp_path, base, base)
    materialized = tmp_path / "materialized-aged"
    _write_tree(materialized, base)
    project = tmp_path / "P-aged"
    run_copy(
        str(materialized),
        str(project),
        data={
            "package_name": PACKAGE,
            "with_ui": False,
            "sdk_version": old,
            "otdp_version": active_version("otdp"),
        },
        defaults=True,
        quiet=True,
    )
    _enforce_lf(project)
    _pin_local_answers(project, repo, _git_out(repo, "rev-parse", BASE_TAG))
    # The project is genuinely aged: bytes and answers both carry the old
    # stamp, and the answers record it.
    assert f"benchweave-sdk {old}".encode() in (project / "AGENTS.md").read_bytes()
    assert f"sdk_version: {old}" in (project / ".copier-answers.yml").read_text(
        encoding="utf-8"
    )
    _author_commit(project)
    conflicted, restored = upgrade_project(project, target_ref=TARGET_TAG)
    assert conflicted == [] and restored == []
    managed = sorted(
        member.removeprefix("template/").removesuffix(".jinja")
        for member in base
        if member == "template/AGENTS.md.jinja" or member.startswith("template/.claude/")
    )
    assert len(managed) == 6, managed
    for relative in managed:
        assert (project / relative).read_bytes() == (
            FIXTURES / "base" / relative
        ).read_bytes(), f"{relative} must re-stamp to the installed SDK's version"


def test_skip_list_is_load_bearing_on_update(tmp_path: Path) -> None:
    """The record's RED control (i), standing: delete _skip_if_exists and
    owned-file preservation fails — the author-edited README loses byte
    purity to the 3-way merge (markers, template bytes landing)."""
    from benchweave_sdk.scaffold_update import upgrade_project

    base = _base_members(tmp_path)
    assert base is not None
    target = dict(_repo_template_members() or {})
    assert target
    for members in (base, target):
        members["copier.yml"] = b"".join(
            line + b"\n"
            for line in members["copier.yml"].splitlines()
            if not line.startswith(b"_skip_if_exists:")
        )
    assert b"_skip_if_exists" not in base["copier.yml"]
    target["template/README.md"] = base["template/README.md"].replace(
        b"# Device plugin starter", b"# Device plugin starter v2"
    )
    repo = _build_tagged_template_repo(tmp_path, base, target)
    materialized = tmp_path / "materialized-noskip"
    _write_tree(materialized, base)
    project = tmp_path / "P-noskip"
    _scaffold_offline(materialized, repo, project)
    readme = project / "README.md"
    author_readme = readme.read_bytes().replace(
        b"# Device plugin starter", b"# AUTHOR plugin"
    )
    readme.write_bytes(author_readme)
    _author_commit(project)
    _conflicted, _restored = upgrade_project(project, target_ref=TARGET_TAG)
    after = readme.read_text(encoding="utf-8")
    assert after != author_readme, "without the skip list A2 must fail"
    assert "<<<<<<< before updating" in after
    assert "# Device plugin starter v2" in after


def test_upgrade_keeps_author_bytes_when_seeds_are_unchanged(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold_update import upgrade_project

    base = _base_members(tmp_path)
    assert base is not None
    target = dict(_repo_template_members() or {})
    assert target
    repo = _build_tagged_template_repo(tmp_path, base, target)
    materialized = tmp_path / "materialized-upg-clean"
    _write_tree(materialized, base)
    project = tmp_path / "P-upgrade-clean"
    _scaffold_offline(materialized, repo, project)
    for relative in ("README.md", "CLAUDE.md", f"src/{PACKAGE}/adapter.py"):
        path = project / relative
        path.write_bytes(path.read_bytes() + AUTHOR_LINE.encode())
    author_state = _tree(project)
    _author_commit(project)
    conflicted, _restored = upgrade_project(project, target_ref=TARGET_TAG)
    assert conflicted == []
    for relative, content in author_state.items():
        if relative == ".copier-answers.yml":
            continue
        assert (project / relative).read_bytes() == content, relative


def test_upgrade_refuses_without_answers_pointing_at_adopt(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold_update import upgrade_project

    project = tmp_path / "P-no-answers"
    project.mkdir()
    (project / "README.md").write_bytes(b"not scaffolded here\n")
    with pytest.raises(ValueError, match=r"^upgrade_answers_missing: ") as refusal:
        upgrade_project(project)
    assert "adopt" in str(refusal.value)


def test_upgrade_refuses_a_non_git_project(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold_update import upgrade_project

    repo, materialized, _target = _upgrade_stage(tmp_path)
    project = tmp_path / "P-no-git"
    _scaffold_offline(materialized, repo, project)  # answers present, no git init
    with pytest.raises(ValueError, match=r"^upgrade_requires_git: ") as refusal:
        upgrade_project(project, target_ref=TARGET_TAG)
    assert "git init" in str(refusal.value)


def test_upgrade_refuses_a_dirty_tree(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold_update import upgrade_project

    repo, materialized, _target = _upgrade_stage(tmp_path)
    project = tmp_path / "P-dirty"
    _scaffold_offline(materialized, repo, project)
    _author_commit(project)
    (project / "README.md").write_bytes(b"uncommitted edit\n")
    with pytest.raises(ValueError, match=r"^upgrade_dirty_tree: ") as refusal:
        upgrade_project(project, target_ref=TARGET_TAG)
    assert "commit" in str(refusal.value).lower()


def test_adopt_writes_exactly_what_new_writes(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk.scaffold_update import adopt_project

    project = tmp_path / "P-adopt"
    create_project(project, PACKAGE)
    expected = (project / ".copier-answers.yml").read_bytes()
    (project / ".copier-answers.yml").unlink()  # the pre-copier project shape
    adopted = adopt_project(project)
    assert adopted == __version__
    assert (project / ".copier-answers.yml").read_bytes() == expected


def test_adopt_infers_with_ui_from_the_ui_guide(tmp_path: Path) -> None:
    from benchweave_sdk.presentation import create_ui_resources
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk.scaffold_update import adopt_project

    project = tmp_path / "P-adopt-ui"
    create_project(project, PACKAGE, with_ui=True)
    create_ui_resources(project, PACKAGE)
    expected = (project / ".copier-answers.yml").read_bytes()
    (project / ".copier-answers.yml").unlink()
    adopt_project(project)
    assert (project / ".copier-answers.yml").read_bytes() == expected


def test_adopt_refuses_when_answers_already_exist(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk.scaffold_update import adopt_project

    project = tmp_path / "P-adopt-present"
    create_project(project, PACKAGE)
    with pytest.raises(ValueError, match=r"^adopt_answers_present: "):
        adopt_project(project)


def test_adopt_refuses_provenance_it_cannot_establish(tmp_path: Path) -> None:
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk.scaffold_update import adopt_project

    project = tmp_path / "P-adopt-unknown"
    create_project(project, PACKAGE)
    (project / ".copier-answers.yml").unlink()
    # No pin to infer from and no override: an unknown base is never claimed.
    pyproject = project / "pyproject.toml"
    pyproject.write_bytes(
        pyproject.read_bytes().replace(
            f'test = ["benchweave-sdk=={__version__}", "pytest>=8.0"]'.encode(),
            b'test = ["pytest>=8.0"]',
        )
    )
    with pytest.raises(ValueError, match=r"^adopt_provenance_unknown: ") as refusal:
        adopt_project(project)
    assert "--scaffolded-at" in str(refusal.value)
    # An unresolvable package name refuses the same way.
    other = tmp_path / "P-adopt-nopkg"
    create_project(other, PACKAGE)
    (other / ".copier-answers.yml").unlink()
    bad = other / "pyproject.toml"
    bad.write_bytes(
        bad.read_bytes().replace(
            f'packages = ["src/{PACKAGE}"]'.encode(), b"packages = []"
        )
    )
    with pytest.raises(ValueError, match=r"^adopt_provenance_unknown: "):
        adopt_project(other)


def test_cli_wires_the_upgrade_and_adopt_refusals(tmp_path: Path) -> None:
    from benchweave_sdk.cli import main
    from benchweave_sdk.scaffold import create_project

    bare = tmp_path / "cli-bare"
    bare.mkdir()
    assert main(["upgrade", str(bare)]) == 1  # upgrade_answers_missing via click
    project = tmp_path / "cli-adopt"
    create_project(project, PACKAGE)
    assert main(["adopt", str(project)]) == 1  # adopt_answers_present via click


# --- adversary fold rows (issue #347 WS2 review) -----------------------------


def test_upgrade_restores_skip_protected_files_the_template_dropped(tmp_path: Path) -> None:
    """B-F1: copier's update deletes project files the template no longer
    renders, skip patterns notwithstanding — skip protects CONTENT, not
    EXISTENCE. The guard snapshots the skip-protected tree, restores what the
    update deleted, and reports it by name: the author's file is never
    silently gone."""
    from benchweave_sdk.scaffold_update import upgrade_project

    base = _base_members(tmp_path)
    assert base is not None
    target = dict(_repo_template_members() or {})
    assert target
    del target["template/tests/test_plugin.py.jinja"]
    del target["template/src/{{ package_name }}/adapter.py.jinja"]
    repo = _build_tagged_template_repo(tmp_path, base, target)
    materialized = tmp_path / "materialized-dropped"
    _write_tree(materialized, base)
    project = tmp_path / "P-dropped"
    _scaffold_offline(materialized, repo, project)
    for relative in ("tests/test_plugin.py", f"src/{PACKAGE}/adapter.py"):
        path = project / relative
        path.write_bytes(path.read_bytes() + b"# AUTHOR EDIT\n")
    _author_commit(project)
    conflicted, restored = upgrade_project(project, target_ref=TARGET_TAG)
    assert conflicted == []
    assert sorted(restored) == [f"src/{PACKAGE}/adapter.py", "tests/test_plugin.py"]
    for relative in ("tests/test_plugin.py", f"src/{PACKAGE}/adapter.py"):
        path = project / relative
        assert path.is_file(), f"{relative} was silently deleted"
        assert "# AUTHOR EDIT" in path.read_text(encoding="utf-8")


def test_upgrade_refuses_a_missing_tag_with_the_typed_prefix(tmp_path: Path) -> None:
    """A-F2: an unreleased/missing template tag refuses typed, naming the tag
    and 'released templates only' — never copier's raw git pathspec noise."""
    from benchweave_sdk.scaffold_update import upgrade_project

    repo, materialized, _target = _upgrade_stage(tmp_path)
    project = tmp_path / "P-tag"
    _scaffold_offline(materialized, repo, project)
    _author_commit(project)
    with pytest.raises(ValueError, match=r"^upgrade_tag_missing: ") as refusal:
        upgrade_project(project, target_ref="v0.0.0-nonexistent")
    message = str(refusal.value)
    assert "v0.0.0-nonexistent" in message
    assert "released templates only" in message


def test_upgrade_refuses_a_wrong_base_tag_with_the_typed_prefix(tmp_path: Path) -> None:
    """B-F4: the tag pre-flight covers the WHOLE resolution class — a wrong
    or unresolvable ``_commit`` (the base) in the answers must surface as
    the same typed refusal, never copier's raw git pathspec traceback."""
    from benchweave_sdk.scaffold_update import upgrade_project

    repo, materialized, _target = _upgrade_stage(tmp_path)
    project = tmp_path / "P-wrongbase-tag"
    _scaffold_offline(materialized, repo, project)
    answers = project / ".copier-answers.yml"
    rendered = [
        line
        for line in answers.read_text(encoding="utf-8").splitlines(keepends=True)
        if not line.startswith("_commit:")
    ]
    rendered[1:1] = ["_commit: v0.0.0-wrong-base\n"]
    answers.write_bytes("".join(rendered).encode())
    _author_commit(project)
    with pytest.raises(ValueError, match=r"^upgrade_tag_missing: ") as refusal:
        upgrade_project(project, target_ref=TARGET_TAG)
    message = str(refusal.value)
    assert "v0.0.0-wrong-base" in message
    assert "base" in message, "the refusal must say which side failed to resolve"


def test_adopted_project_first_upgrade_conflicts_honestly_on_managed_edits(
    tmp_path: Path,
) -> None:
    """A-F1: adopting pins a base tag whose tree predates the template, so
    the first upgrade cannot explain any project file. Unedited files ride
    the parity back-check cleanly; an author-edited MANAGED file (AI-GUIDE,
    matched by no skip pattern) comes back as a reported conflict with both
    sides intact — data-safe, and the help text discloses exactly this."""
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk.scaffold_update import upgrade_project

    base = _base_members(tmp_path)
    assert base is not None
    target = dict(_repo_template_members() or {})
    assert target
    repo = tmp_path / "template-repo-pre"
    repo.mkdir()
    _git_init(repo)
    (repo / "README.md").write_bytes(
        b"a pre-copier SDK repo: no copier.yml, no template\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "pre-copier")
    _git(repo, "tag", "v0.8.0")
    _write_tree(repo, target)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "target")
    _git(repo, "tag", TARGET_TAG)

    project = tmp_path / "P-adopted-first"
    create_project(project, PACKAGE)
    guide = project / "AI-GUIDE.md"
    guide.write_bytes(
        guide.read_bytes().replace(
            b"# Build a BenchWeave device plugin with AI", b"# AUTHOR-customised guide"
        )
    )
    answers = project / ".copier-answers.yml"
    rendered = [
        line
        for line in answers.read_text(encoding="utf-8").splitlines(keepends=True)
        if not line.startswith(("_commit:", "_src_path:"))
    ]
    rendered[1:1] = [
        f"_commit: {_git_out(repo, 'rev-parse', 'v0.8.0')}\n",
        f"_src_path: {repo}\n",
    ]
    answers.write_bytes("".join(rendered).encode())
    _author_commit(project)
    conflicted, restored = upgrade_project(project, target_ref=TARGET_TAG)
    assert conflicted == ["AI-GUIDE.md"]
    assert restored == []
    text = guide.read_text(encoding="utf-8")
    assert "<<<<<<< before updating" in text
    assert "AUTHOR-customised guide" in text, "the author's line survives the add/add conflict"


def test_upgrade_help_discloses_the_adopted_project_shape() -> None:
    """A-F1: the help must not claim conflicts only happen where author and
    template both changed a file — an adopted project's first upgrade
    conflicts on any author-edited file the old base never rendered."""
    from click.testing import CliRunner

    from benchweave_sdk.cli import cli

    result = CliRunner().invoke(cli, ["upgrade", "--help"])
    assert result.exit_code == 0
    assert "adopted" in result.output


def test_upgrade_resolves_a_symlinked_project_path(tmp_path: Path) -> None:
    """A-F4: the function resolves its target the way the CLI does — copier
    compares canonical git prefixes and refuses mixed spellings."""
    from benchweave_sdk.scaffold_update import upgrade_project

    repo, materialized, _target = _upgrade_stage(tmp_path)
    project = tmp_path / "P-resolve"
    _scaffold_offline(materialized, repo, project)
    _author_commit(project)
    link = tmp_path / "P-resolve-link"
    try:
        link.symlink_to(project, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    conflicted, restored = upgrade_project(link, target_ref=TARGET_TAG)
    assert conflicted == [] and restored == []


def test_adopt_refuses_a_dangling_symlink_answers_file(tmp_path: Path) -> None:
    """A-F3: a dangling symlink occupying the answers name counts as present
    (the create_project destination-guard precedent) — writing through it
    would materialise the link's target outside the project's intent."""
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk.scaffold_update import adopt_project

    project = tmp_path / "P-adopt-link"
    create_project(project, PACKAGE)
    (project / ".copier-answers.yml").unlink()
    try:
        (project / ".copier-answers.yml").symlink_to(project / "nowhere.yml")
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    with pytest.raises(ValueError, match=r"^adopt_answers_present: "):
        adopt_project(project)
    assert (project / ".copier-answers.yml").is_symlink(), "the link itself is left alone"
    assert not (project / "nowhere.yml").exists(), "nothing was written through the link"
