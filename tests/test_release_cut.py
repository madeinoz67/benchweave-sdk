"""The release-cut transaction (issue #408 S1): the bump carries its blast radius.

The registry, the occurrence validation, the phase-2 computation and the
``--verify`` verdict are pure functions over fixture texts; the orchestration
is exercised in-process against synthetic mini-repositories with the external
legs (uv sync-standards --check, the scaffold pytest suite) monkeypatched —
no arm touches the network and no arm writes inside THIS checkout.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_cut.py"

OLD = "0.7.1"
NEW = "0.8.0"


def _synth(seed: str) -> str:
    """A deterministic synthetic 40-hex SHA — invented, never a real object."""
    return (seed * 5)[:40]


def _load() -> Any:
    """Load the script ONCE per session: the arms patch module globals, so
    fixture and test must share one module instance."""
    existing = sys.modules.get("release_cut_under_test")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("release_cut_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- synthetic trees -----------------------------------------------------------


def _pyproject(version: str) -> str:
    return (
        "[project]\n"
        f'name = "benchweave-sdk"\nversion = "{version}"\n'
        'description = "synthetic"\n'
    )


def _uv_lock(version: str) -> str:
    return (
        "version = 1\n"
        "requires-python = \">=3.13\"\n"
        "\n"
        "[[package]]\n"
        f'name = "benchweave-sdk"\nversion = "{version}"\n'
        'source = { editable = "." }\n'
    )


def _readme(version: str) -> str:
    return (
        "# Synthetic SDK\n\n"
        f"Python 3.13+, SDK {version}, OTDP 0.2.2 and adapter API 1.1 are the baseline.\n"
    )


def _website(version: str) -> str:
    return (
        "<html><body>\n"
        '  <div class="status-line"><span class="status-dot"></span> '
        f"SDK {version} · OTDP 0.2.2 · adapter API 1.1</div>\n"
        "  <select class=\"version-select\" onchange=\"gotoVersion(this)\" "
        'aria-label="Documentation version">\n'
        f'          <option value="docs/">v{version} (latest)</option>\n'
        '          <option value="docs/v/v0.6.0/">v0.6.0</option>\n'
        "  </select>\n"
        f'  <p class="tagline">Compatibility: SDK {version} against the main '
        "repository <code>&gt;=0.1.0</code>.</p>\n"
        "</body></html>\n"
    )


def _lock(version: str) -> str:
    # compact, like the lock file actually ships (single line, no space
    # after the colon) — the replay arm caught the spaced shape matching 0
    return json.dumps(
        {"compatibility": {"main_project": ">=0.1.0", "sdk": version}, "standards": []},
        separators=(",", ":"),
    )


def _great_docs(version: str) -> str:
    return (
        "hero:\n"
        "  title: synthetic\n"
        "versions:\n"
        f"  - tag: v{version}\n"
        f"    label: v{version}\n"
        "    latest: true          # latest stable lives at the docs/ root\n"
        f"    git_ref: v{version}\n"
        "  - tag: v0.6.0\n"
        "    label: v0.6.0\n"
        "    latest: false\n"
        "    git_ref: v0.6.0\n"
    )


MINI_TREE: dict[str, str] = {
    "pyproject.toml": _pyproject(OLD),
    "uv.lock": _uv_lock(OLD),
    "README.md": _readme(OLD),
    "website/index.html": _website(OLD),
    "standards-lock.json": _lock(OLD),
    "great-docs.yml": _great_docs(OLD),
    "docs/internal/release-review-matrix.md": "# Release-review matrix\n\nrows\n",
}


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def _tree_for(version: str) -> dict[str, str]:
    return {
        "pyproject.toml": _pyproject(version),
        "uv.lock": _uv_lock(version),
        "README.md": _readme(version),
        "website/index.html": _website(version),
        "standards-lock.json": _lock(version),
        "great-docs.yml": _great_docs(version),
        "docs/internal/release-review-matrix.md": "# Release-review matrix\n\nrows\n",
    }


def _mini_repo(
    tmp_path: Path,
    *,
    version: str = OLD,
    tag: bool = True,
    doctor: dict[str, str] | None = None,
) -> Path:
    """A synthetic SDK repository: the seven declared files, one commit, the
    release tag. Identity is repo-local so no ambient git config matters.
    `doctor` overrides seeded content BEFORE the commit, so a test can plant
    a malformed surface without dirtying the tree."""
    repo = tmp_path / "sdk"
    seeded = _tree_for(version)
    if doctor:
        seeded.update(doctor)
    for relative, text in seeded.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (repo / "tests" / "fixtures" / "scaffold_expected" / "base").mkdir(
        parents=True, exist_ok=True
    )
    (repo / "tests" / "fixtures" / "scaffold_expected" / "ui").mkdir(
        parents=True, exist_ok=True
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "synthetic-operator")
    _git(repo, "config", "user.email", "operator@example.invalid")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    if tag:
        _git(repo, "tag", "-a", f"v{version}", "-m", "synthetic release")
    return repo


@pytest.fixture()
def cut_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A mini-repo whose external legs are no-op successes: the real
    sync-standards check and scaffold suite need a real checkout; the
    orchestration arms here pin the wiring, and the harness replays the
    legs for real (the design record's section 9)."""
    repo = _mini_repo(tmp_path)
    drift = _load()
    ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(drift, "run_command", lambda cmd, *, cwd: ok)
    monkeypatch.setattr(drift, "regenerate_fixtures", lambda root, version: None)
    return repo


# --- the registry: the declared-surface census ---------------------------------


def test_registry_names_exactly_the_declared_version_surfaces() -> None:
    """The declared-surface registry IS the census: six substitution
    patterns across five files (the website file carries the hero and the
    tagline patterns in one row), one regen, one derived and two phase-2
    rows — set-equal, so an unregistered bump-sensitive surface is visible
    as a registry diff."""
    drift = _load()
    pairs = sorted((s.path, s.kind) for s in drift.DECLARED_SURFACES)
    assert pairs == [
        ("README.md", "substitution"),
        ("docs/internal/release-review-matrix.md", "derived"),
        ("great-docs.yml", "phase2"),
        ("pyproject.toml", "substitution"),
        ("standards-lock.json", "substitution"),
        ("tests/fixtures/scaffold_expected", "regen"),
        ("uv.lock", "substitution"),
        ("website/index.html", "phase2"),
        ("website/index.html", "substitution"),
    ]
    # PATTERN-level census (the m1 lesson): a removed PATTERN is invisible to
    # the runtime cut (the tool cannot see what it does not declare) and to
    # a path-level census — the pattern set itself is the pinned surface.
    by_path = {}
    for surface in drift.DECLARED_SURFACES:
        by_path.setdefault(surface.path, []).extend(
            template for template, _expected in surface.patterns
        )
    assert sorted(by_path["website/index.html"]) == [
        "</span> SDK {v} ·",
        "Compatibility: SDK {v} against",
    ]
    assert by_path["pyproject.toml"] == ['version = "{v}"']
    assert by_path["standards-lock.json"] == ['"sdk":"{v}"']


def test_occurrence_mismatch_names_file_pattern_and_counts() -> None:
    """The cargo-release discipline: a pattern must match exactly its
    expected count or the cut aborts naming file, pattern, expected, found."""
    drift = _load()
    texts = {path: text for path, text in MINI_TREE.items()}
    texts["README.md"] = _readme(OLD) + _readme(OLD)  # the pattern would count 2
    problems = drift.validate_occurrences(texts, OLD)
    assert any(
        "README.md" in problem and "expected 1" in problem and "found 2" in problem
        for problem in problems
    ), problems


def test_validate_flags_a_missing_declared_file() -> None:
    drift = _load()
    texts = {path: text for path, text in MINI_TREE.items()}
    del texts["standards-lock.json"]
    problems = drift.validate_occurrences(texts, OLD)
    assert any("standards-lock.json" in problem and "missing" in problem for problem in problems)


# --- substitutions --------------------------------------------------------------


def test_substitutions_move_all_six_patterns_old_to_new() -> None:
    drift = _load()
    texts = {path: text for path, text in MINI_TREE.items()}
    moved = drift.apply_substitutions(texts, OLD, NEW)
    assert moved["pyproject.toml"] == _pyproject(NEW)
    assert moved["uv.lock"] == _uv_lock(NEW)
    assert moved["README.md"] == _readme(NEW)
    assert moved["standards-lock.json"] == _lock(NEW)
    assert f"SDK {NEW} ·" in moved["website/index.html"]
    assert f"Compatibility: SDK {NEW} against" in moved["website/index.html"]


# --- preflight refusals -----------------------------------------------------------


def test_non_increment_version_is_refused(tmp_path: Path) -> None:
    drift = _load()
    with pytest.raises(drift.ReleaseCutError, match="version_not_an_increment"):
        drift.assert_increment(OLD, "0.6.9")
    with pytest.raises(drift.ReleaseCutError, match="version_not_an_increment"):
        drift.assert_increment(OLD, OLD)
    with pytest.raises(drift.ReleaseCutError, match="version_malformed"):
        drift.parse_version("0.8")


def test_recut_over_a_cut_tree_needs_force(tmp_path: Path) -> None:
    drift = _load()
    repo = _mini_repo(tmp_path, version=NEW)
    with pytest.raises(drift.ReleaseCutError, match="already_at_version"):
        drift.check_recut(repo, NEW, force=False)
    drift.check_recut(repo, NEW, force=True)  # --force re-runs the same version


def test_dirty_tree_is_refused(tmp_path: Path) -> None:
    drift = _load()
    repo = _mini_repo(tmp_path)
    (repo / "README.md").write_text(
        _readme(OLD) + "\nstray edit\n", encoding="utf-8"
    )
    with pytest.raises(drift.ReleaseCutError, match="tree_not_clean"):
        drift.assert_clean_tree(repo)


def test_git_verb_whitelist_refuses_write_and_network_verbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is structural: release-cut's only git entry point
    whitelists the read-only verbs — commit, tag creation, push and every
    network verb are refused by construction, not by discipline."""
    drift = _load()
    repo = _mini_repo(tmp_path)
    for refused in (
        ("commit", "-m", "x"),
        ("tag", "v9.9.9"),
        ("push", "origin", "main"),
        ("fetch", "origin"),
        ("ls-remote", "origin"),
        ("pull",),
        ("tag", "-d", "v0.7.1"),
        ("apply", "x.patch"),
        ("add", "README.md"),
        ("checkout", "-b", "x"),
    ):
        with pytest.raises(drift.ReleaseCutError, match="read-only git verbs only"):
            drift._git(repo, *refused)
    for allowed in (
        ("status", "--porcelain"),
        ("log", "--oneline", "-1"),
        ("rev-parse", "HEAD"),
        ("tag", "-l"),
        ("show", f"v{OLD}:standards-lock.json"),
        ("diff", "--stat", f"v{OLD}..HEAD"),
    ):
        drift._git(repo, *allowed)  # must not raise


# --- the cut, end to end (external legs monkeypatched) ----------------------------


def test_cut_moves_the_tree_and_emits_plan_and_patch(cut_env: Path) -> None:
    drift = _load()
    repo = cut_env
    assert drift.main([NEW, "--repo", str(repo)]) == 0
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == _pyproject(NEW)
    assert (repo / "README.md").read_text(encoding="utf-8") == _readme(NEW)
    lock = json.loads((repo / "standards-lock.json").read_text(encoding="utf-8"))
    assert lock["compatibility"]["sdk"] == NEW
    plan = json.loads((repo / ".release" / "plan.json").read_text(encoding="utf-8"))
    assert plan["version"] == NEW
    assert plan["prev_tag"] == f"v{OLD}"
    assert plan["base_sha"], "base_sha must be recorded"
    assert any(
        s["path"] == "pyproject.toml" and s["kind"] == "substitution"
        for s in plan["surfaces"]
    )
    patch = (repo / ".release" / f"phase2-v{NEW}.patch").read_text(encoding="utf-8")
    assert "a/great-docs.yml" in patch and "a/website/index.html" in patch
    matrix = (repo / "docs/internal/release-review-matrix.md").read_text(encoding="utf-8")
    assert f"## Result record — v{NEW}" in matrix
    assert "occurrence-validated" in matrix


def test_two_pass_no_write_when_any_pattern_mismatches(tmp_path: Path) -> None:
    """Nothing is written before every pattern validates: a doctored surface
    (seeded BEFORE the commit, so the dirty-tree preflight cannot be what
    refuses) aborts the whole cut and the tree is byte-identical afterwards."""
    drift = _load()
    repo = _mini_repo(
        tmp_path, doctor={"README.md": _readme(OLD) + _readme(OLD)}
    )
    before = {p: (repo / p).read_bytes() for p in MINI_TREE}
    assert drift.main([NEW, "--repo", str(repo)]) == 1
    for path, content in before.items():
        assert (repo / path).read_bytes() == content, path
    assert not (repo / ".release").exists()


def test_cut_restores_the_tree_when_a_later_stage_fails(tmp_path: Path) -> None:
    """A failure after the substitutions (here: the scaffold suite red) puts
    the tree back: the cut is all-or-nothing, not partially applied."""
    repo = _mini_repo(tmp_path)
    before = {p: (repo / p).read_bytes() for p in MINI_TREE}
    real = importlib.util.spec_from_file_location("rc_real", SCRIPT)
    assert real is not None and real.loader is not None
    module = importlib.util.module_from_spec(real)
    sys.modules["rc_real"] = module
    real.loader.exec_module(module)
    red = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="red")
    module.run_command = lambda cmd, *, cwd: red  # the post-cut pytest leg fails
    module.regenerate_fixtures = lambda root, version: None
    assert module.main([NEW, "--repo", str(repo)]) == 1
    for path, content in before.items():
        assert (repo / path).read_bytes() == content, path
    assert not (repo / ".release").exists()


# --- the phase-2 computation --------------------------------------------------------


def test_phase2_registers_the_new_version_and_demotes_the_old() -> None:
    drift = _load()
    new_yml, new_html = drift.build_phase2(_great_docs(OLD), _website(OLD), NEW)
    assert new_yml.index(f"tag: v{NEW}") < new_yml.index(f"tag: v{OLD}")
    assert new_yml.count("latest: true") == 1
    assert f"- tag: v{NEW}" in new_yml
    assert f"- tag: v{OLD}" in new_yml
    assert 'value="docs/v/v0.6.0/">v0.6.0</option>' in new_html  # untouched option survives
    assert f'value="docs/">v{NEW} (latest)</option>' in new_html
    assert f'value="docs/v/v{OLD}/">v{OLD}</option>' in new_html
    assert new_html.count("(latest)") == 1


def test_phase2_refuses_double_registration_and_latest_ambiguity() -> None:
    drift = _load()
    with pytest.raises(drift.ReleaseCutError, match="phase2_already_registered"):
        drift.build_phase2(_great_docs(NEW), _website(OLD), NEW)
    ambiguous = _great_docs(OLD).replace(
        "    latest: false\n    git_ref: v0.6.0\n",
        "    latest: true\n    git_ref: v0.6.0\n",
    )
    with pytest.raises(drift.ReleaseCutError, match="phase2_latest_ambiguity"):
        drift.build_phase2(ambiguous, _website(OLD), NEW)


def test_phase2_patch_is_exactly_two_files_and_applies_on_the_real_tree() -> None:
    """Against THIS checkout's real great-docs.yml and selector: the emitted
    patch names exactly the two registration surfaces and git apply --check
    accepts it — the tag-commit rehearsal in miniature."""
    drift = _load()
    great_docs = (ROOT / "great-docs.yml").read_text(encoding="utf-8")
    selector = (ROOT / "website" / "index.html").read_text(encoding="utf-8")
    current = drift.current_version(ROOT)
    major, minor, micro = (int(part) for part in current.split("."))
    next_version = f"{major}.{minor}.{micro + 1}"
    new_yml, new_html = drift.build_phase2(great_docs, selector, next_version)
    patch = drift.unified_patch("great-docs.yml", great_docs, new_yml) + drift.unified_patch(
        "website/index.html", selector, new_html
    )
    paths = drift.patch_paths(patch)
    assert paths == {"great-docs.yml", "website/index.html"}
    with _scratch_copy_of_repo_files(ROOT, ["great-docs.yml", "website/index.html"]) as scratch:
        proc = subprocess.run(
            ["git", "apply", "--check", "-"],
            input=patch,
            capture_output=True,
            text=True,
            cwd=scratch,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr


def _scratch_copy_of_repo_files(root: Path, files: list[str]):  # noqa: ANN201
    """git apply needs a work tree; a bare dir with the two files and a
    throwaway git index is enough (no commit is made)."""
    import contextlib
    import tempfile

    @contextlib.contextmanager
    def _ctx():
        with tempfile.TemporaryDirectory() as raw:
            scratch = Path(raw).resolve()
            for relative in files:
                source = root / relative
                target = scratch / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            subprocess.run(
                ["git", "init", "-q", "-b", "main"],
                cwd=scratch,
                capture_output=True,
                timeout=60,
                check=True,
            )
            yield scratch

    return _ctx()


# --- --verify ------------------------------------------------------------------------


def test_verify_is_green_on_a_cut_tree(cut_env: Path) -> None:
    drift = _load()
    assert drift.main([NEW, "--repo", str(cut_env)]) == 0
    assert drift.main(["--verify", "--repo", str(cut_env)]) == 0


def test_verify_red_when_the_anchor_is_skipped(cut_env: Path) -> None:
    """The v0.7.0 defect replayed: compatibility.sdk left at the old version
    while the tree moved — --verify reds, naming the anchor (root cause d)."""
    drift = _load()
    assert drift.main([NEW, "--repo", str(cut_env)]) == 0
    # Anchor-only failure: the RAW text keeps the pattern parity ("sdk":
    # "0.8.0" counted once, inside a decoy string) while the PARSED
    # compatibility.sdk stays at the old version — the v0.7.0 class in
    # isolation, so this arm cannot pass via the occurrence check.
    doctored = (
        '{"compatibility": {"main_project": ">=0.1.0", "sdk": "' + OLD + '"}, '
        '"standards": [], "decoy": "\"sdk\": \"' + NEW + '\""}'
    )
    (cut_env / "standards-lock.json").write_text(doctored, encoding="utf-8")
    assert drift.main(["--verify", "--repo", str(cut_env)]) == 1


def test_verify_red_when_a_surface_is_left_stale(cut_env: Path) -> None:
    """The m1 shape: a surface the registry declares but the cut skipped —
    --verify reds naming the stale file."""
    drift = _load()
    assert drift.main([NEW, "--repo", str(cut_env)]) == 0
    (cut_env / "README.md").write_text(_readme(OLD), encoding="utf-8")
    assert drift.main(["--verify", "--repo", str(cut_env)]) == 1


def test_verify_red_when_the_patch_is_missing(cut_env: Path) -> None:
    drift = _load()
    assert drift.main([NEW, "--repo", str(cut_env)]) == 0
    (cut_env / ".release" / f"phase2-v{NEW}.patch").unlink()
    assert drift.main(["--verify", "--repo", str(cut_env)]) == 1


def test_verify_red_when_the_patch_touches_a_third_file(cut_env: Path) -> None:
    drift = _load()
    assert drift.main([NEW, "--repo", str(cut_env)]) == 0
    patch = cut_env / ".release" / f"phase2-v{NEW}.patch"
    readme = (cut_env / "README.md").read_text(encoding="utf-8")
    patch.write_text(
        patch.read_text(encoding="utf-8")
        # a third hunk that applies cleanly to an existing file, so ONLY the
        # file-set assertion can fail — git apply --check stays green
        + drift.unified_patch("README.md", readme, readme + "<!-- extra -->\n"),
        encoding="utf-8",
    )
    assert drift.main(["--verify", "--repo", str(cut_env)]) == 1


def test_verify_red_when_the_patch_no_longer_applies(cut_env: Path) -> None:
    """main moved between merge and tag-cut: the staged patch conflicts —
    --verify fails loudly (the answer is --phase2-only regeneration)."""
    drift = _load()
    assert drift.main([NEW, "--repo", str(cut_env)]) == 0
    (cut_env / "great-docs.yml").write_text("versions:\n  - tag: v9.9.9\n", encoding="utf-8")
    assert drift.main(["--verify", "--repo", str(cut_env)]) == 1


# --- fixture regeneration -------------------------------------------------------------


def test_fixture_regen_reproduces_the_committed_fixture_bytes(tmp_path: Path) -> None:
    """The regen mechanism renders both arms under a RESOLVED tempdir (the
    macOS /var symlink gotcha is designed in) and reproduces the committed
    fixtures byte for byte at the installed version — the same claim the
    byte-parity suite pins, exercised through the tool's own path."""
    from benchweave_sdk import __version__

    drift = _load()
    scratch = tmp_path / "fixtures"
    drift.regenerate_fixtures(scratch, __version__)
    for arm in ("base", "ui"):
        rendered = _tree(scratch / arm)
        committed = _tree(ROOT / "tests" / "fixtures" / "scaffold_expected" / arm)
        assert sorted(rendered) == sorted(committed), arm
        for relative in committed:
            assert rendered[relative] == committed[relative], f"{arm}/{relative}"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        entry.relative_to(root).as_posix(): entry.read_bytes()
        for entry in sorted(root.rglob("*"))
        if entry.is_file()
    }


def test_canonical_pin_rewrites_the_answers(tmp_path: Path) -> None:
    drift = _load()
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".copier-answers.yml").write_bytes(
        b"# Changes here will be overwritten by Copier\n"
        b"_commit: v0.0.0\n"
        b"_src_path: /tmp/somewhere-ephemeral\n"
        b"sdk_version: 0.0.0\n"
    )
    drift.canonical_pin_answers(project, NEW)
    raw = (project / ".copier-answers.yml").read_bytes()
    assert b"_commit: v" + NEW.encode() in raw
    assert b"_src_path: https://github.com/madeinoz67/benchweave-sdk" in raw


# --- the matrix scaffold ---------------------------------------------------------------


def test_matrix_scaffold_pre_fills_every_row_and_guesses_no_class() -> None:
    drift = _load()
    matrix = (ROOT / "docs" / "internal" / "release-review-matrix.md").read_text(
        encoding="utf-8"
    )
    scaffold = drift.matrix_scaffold(
        version=NEW,
        date="2026-10-06",
        prev_tag=f"v{OLD}",
        contributors="16 commits — authors: synthetic-operator; the walk acknowledges",
        served_set="n-a — no served-set motion in the window",
    )
    appended = matrix + scaffold
    assert f"## Result record — v{NEW} (2026-10-06)" in appended
    for row_number in range(1, 10):
        assert f"| {row_number} |" in scaffold
        assert row_number != 0  # the row set is 1..9, one line each
    assert "PHASE-2" in scaffold
    assert f"`.release/phase2-v{NEW}.patch`" in scaffold
    # D7: the tool never guesses MINOR/PATCH — no class verdict in the scaffold.
    assert "MINOR class:" not in scaffold
    assert "PATCH class:" not in scaffold


# --- governor fold wave: F1 corpus-path refusal, F2 matrix-vs-registry, NIT gate pins ---


def test_registry_cannot_declare_corpus_paths() -> None:
    """F1: the vendored standards corpus is byte-frozen and copy-never-move;
    a corpus-path registration is a structural-impossibility class and the
    loader refuses it loudly (the planted registration here names a real
    corpus-layout path)."""
    drift = _load()
    planted = (
        *drift.DECLARED_SURFACES,
        drift.DeclaredSurface(
            "src/benchweave_sdk/standards/otdp/0.2.2/otdp-runtime.schema.json",
            "substitution",
            "planted corpus row — must be refused",
            (('"version": "{v}"', 1),),
        ),
    )
    with pytest.raises(drift.ReleaseCutError, match="corpus_path_refused"):
        drift.assert_no_corpus_paths(planted)


def test_main_refuses_a_corpus_path_registration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """F1 end to end: main() runs the loader assertion before anything
    else, so a planted corpus row refuses every mode."""
    drift = _load()
    repo = _mini_repo(tmp_path)
    planted = (
        *drift.DECLARED_SURFACES,
        drift.DeclaredSurface(
            "standards/execution/0.2.0/procedure.schema.json",
            "substitution",
            "planted corpus row — must be refused",
            (),
        ),
    )
    monkeypatch.setattr(drift, "DECLARED_SURFACES", planted)
    assert drift.main(["--verify", "--repo", str(repo)]) == 1
    assert "corpus_path_refused" in capsys.readouterr().err


def test_env_refresh_syncs_the_ci_sdk_job_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    """NIT F4b: the cut's env refresh must sync the SAME extras the CI sdk
    job does (test, server, scaffold) — a bare refresh drops the scaffold
    extra and the next fixture render (copier) fails on the missing
    module."""
    drift = _load()
    captured: list[list[str]] = []

    def _spy(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        captured.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drift, "run_command", _spy)
    repo = _mini_repo(Path(tempfile.mkdtemp()))
    drift.main([NEW, "--repo", str(repo)])
    syncs = [cmd for cmd in captured if "sync" in cmd]
    assert syncs, f"the env-refresh sync never ran; commands seen: {captured}"
    for extra in ("test", "server", "scaffold"):
        assert extra in syncs[0], syncs[0]


def test_matrix_test_surfaces_match_the_registry() -> None:
    """F2: the matrix's Test-surfaces prose set is regenerable from the
    mechanism (G4): each T-row is either DECLARED in the registry or
    classified by the prose itself (T3 = a procedure docstring, T4 = inert
    by design) — and the arm fails if the prose and the registry drift
    apart in either direction."""
    drift = _load()
    matrix = (ROOT / "docs" / "internal" / "release-review-matrix.md").read_text(
        encoding="utf-8"
    )
    section = matrix[matrix.find("## Test surfaces"):]
    section = section[: section.find("\n## ", 1)]
    rows = re.findall(r"^\| (T\d+) \| ([^|]+) \|", section, re.M)
    by_id = {row_id: surface.strip() for row_id, surface in rows}
    assert set(by_id) == {"T1", "T2", "T3", "T4"}, by_id
    regen_paths = {
        surface.path for surface in drift.DECLARED_SURFACES if surface.kind == "regen"
    }
    # T1/T2 are the two fixture arms — declared as the one regen surface
    assert "scaffold_expected" in by_id["T1"] and "scaffold_expected" in by_id["T2"]
    assert regen_paths == {"tests/fixtures/scaffold_expected"}
    # T3 is the copier test's docstring — a procedure pointer, not a surface
    assert "test_scaffold_copier.py" in by_id["T3"]
    assert "test_scaffold_copier.py" not in {s.path for s in drift.DECLARED_SURFACES}
    # T4 is inert BY DESIGN — the prose says so, and the registry agrees
    assert "test_scaffold_update" in by_id["T4"]
    assert "test_scaffold_update" not in {s.path for s in drift.DECLARED_SURFACES}


# --- the Makefile wrapper ----------------------------------------------------------------


def test_makefile_wraps_the_script_with_the_env_pin() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "UV_PROJECT_ENVIRONMENT := venv" in makefile
    assert "release-cut:" in makefile
    assert "scripts/release_cut.py $(VERSION)" in makefile


def test_help_states_the_refusals(capsys: pytest.CaptureFixture[str]) -> None:
    drift = _load()
    with pytest.raises(SystemExit) as excinfo:
        drift.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "no commit" in out or "read-only" in out
    assert "--verify" in out
