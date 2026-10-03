"""R-4 — the update promise, per-push lane (issue #347 WS2, design §6).

Protocol: scaffold a project from the repository's template history at its
newest template-touching ancestor (BASE), apply ``new``'s answers-pin
discipline against a throwaway tagged template repository, author-edit three
owned files, commit, then ``copier.run_update`` to the current template and
assert A1-A5:

- A1 managed: ``AI-GUIDE.md`` byte-equal to the current template's render
  (equality, not "changed" — a no-delta push still asserts meaningfully).
- A2 owned: every author-edited owned file byte-identical to the author
  state. Mechanism-honest scope (spike re-proof, disclosed against the
  record's §1 table): in copier 9.18.2 ``_skip_if_exists`` is INERT on
  update — owned preservation comes from the 3-way merge base. Owned seeds
  the template changed between BASE and target are merged, not skipped: an
  author-edited one ends in conflict markers with both sides intact (the
  wrong-base test below pins that nothing is silently lost), and the landing
  push has an empty changed-seed set, so A2 is straight byte-equality here.
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
from benchweave_sdk.scaffold import _repo_template_members  # noqa: PLC2701
from benchweave_sdk.served import active_version

REPO = Path(__file__).resolve().parents[1]
PACKAGE = "example_plugin"
AUTHOR_LINE = "AUTHOR NOTE: my device-specific line\n"
BASE_TAG = "v0.9.0"
TARGET_TAG = "v0.9.1"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )


def _git_out(cwd: Path, *args: str) -> str:
    return _git(cwd, *args).stdout.strip()


def _tree(root: Path) -> dict[str, bytes]:
    """Working-tree files only — ``.git`` internals (the index the update
    rewrites) are not project content."""
    return {
        entry.relative_to(root).as_posix(): entry.read_bytes()
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
    answers.write_text("".join(kept), encoding="utf-8")


def _build_tagged_template_repo(
    tmp: Path, base: dict[str, bytes], target: dict[str, bytes]
) -> Path:
    repo = tmp / "template-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
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
        path.write_text(path.read_text(encoding="utf-8") + AUTHOR_LINE, encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "-c", "user.email=author@benchweave", "-c", "user.name=author",
         "commit", "-qm", "author state")
    author_state = _tree(project)

    # Owned seeds the template changed between BASE and target: these merge
    # on update (3-way), everything else must come through byte-identical.
    changed = sorted(
        relative.removeprefix("template/")
        for relative in set(base) | set(target)
        if base.get(relative) != target.get(relative)
    )

    from copier import run_update

    run_update(str(project), defaults=True, vcs_ref=TARGET_TAG, overwrite=True, quiet=True)
    updated = _tree(project)

    # A1 managed: byte-equal to the current template render.
    assert updated["AI-GUIDE.md"] == target["template/AI-GUIDE.md"]

    # A2 owned: the author's three files plus every unchanged-seed owned
    # file survive byte-identically.
    for relative in ("README.md", "CLAUDE.md", f"src/{PACKAGE}/adapter.py"):
        if relative in changed:
            # Mechanism-honest arm (no landing-push coverage; future pushes):
            # author lines survive inside the conflict block, nothing lost.
            assert AUTHOR_LINE in updated[relative].decode("utf-8")
            assert "<<<<<<< before updating" in updated[relative].decode("utf-8")
        else:
            assert updated[relative] == author_state[relative], relative
    for relative, content in author_state.items():
        if relative in changed or relative == ".copier-answers.yml":
            continue
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
    assert "_commit:" not in (project / ".copier-answers.yml").read_text(encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "-c", "user.email=author@benchweave", "-c", "user.name=author",
         "commit", "-qm", "author state")
    from copier.errors import UserMessageError

    with pytest.raises(UserMessageError, match="cannot obtain old template references"):
        run_update(str(project), defaults=True, vcs_ref=TARGET_TAG, overwrite=True, quiet=True)


def test_wrong_base_provenance_never_silently_loses_author_bytes(tmp_path: Path) -> None:
    """A2's teeth (the honest substitute for the record's control (i) —
    deleting ``_skip_if_exists`` is provably inert on update, spike P5==P6):
    when the pinned base names template state whose seeds differ from what
    the author actually has, the update mis-attributes the delta and the
    author's lines survive only inside conflict markers. Wrong provenance is
    loud, never silent."""
    from copier import run_copy, run_update

    base = _base_members(tmp_path)
    assert base is not None
    target = _repo_template_members()
    assert target is not None
    # A third state A0: the base with a DIFFERENT adapter seed lineage, so
    # the pinned base cannot explain the project's adapter bytes.
    a0 = dict(base)
    a0["template/src/{{ package_name }}/adapter.py"] = (
        a0["template/src/{{ package_name }}/adapter.py"].replace(
            b"def create_plugin():", b"def create_plugin_a0():"
        )
    )
    repo = tmp_path / "template-repo-a0"
    repo.mkdir()
    _git(repo, "init", "-q")
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
    _pin_local_answers(project, repo, _git_out(repo, "rev-parse", "v0.8.0"))
    # The author's real lineage is the BASE adapter, and they renamed the
    # entry point — so on the def line all three states disagree (A0 says
    # create_plugin_a0, the author says create_plugin_author, the target
    # says create_plugin): the wrong base cannot attribute the delta and
    # the merge must conflict rather than pick a side silently.
    adapter = project / "src" / PACKAGE / "adapter.py"
    author_bytes = base["template/src/{{ package_name }}/adapter.py"].replace(
        b"def create_plugin():", b"def create_plugin_author():"
    )
    adapter.write_bytes(author_bytes)
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "-c", "user.email=author@benchweave", "-c", "user.name=author",
         "commit", "-qm", "author state")
    run_update(str(project), defaults=True, vcs_ref=TARGET_TAG, overwrite=True, quiet=True)
    text = adapter.read_text(encoding="utf-8")
    assert "<<<<<<< before updating" in text
    assert "def create_plugin_author():" in text, "the author's rename must survive the merge"
    assert "def create_plugin():" in text, "the template's own line must also be present"
