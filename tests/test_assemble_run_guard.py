"""The done_marker guard on assemble_docs_site.run() (issue #476, design §5.2).

The CI defect does not reproduce on this machine (design §2.3 — the local
great-docs 0.17.0 run exits cleanly), so these arms reproduce the measured
CI shape synthetically: a child that prints the 0.17.0 completion banner,
then never exits, holding sleeping grandchildren in its process group (the
two python3.13 orphans of cancelled run 38758274375). The acceptance rule's
RED control (mechanism disabled, elapsed >= 18s, orphans surviving) is an
out-of-band review-time run, not a suite arm — it exists to contrast with
arm (a), and a suite that re-proves today's bug on every push would burn
20 seconds of every lane to prove nothing new.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "assemble_docs_site.py"

# The repo's POSIX-only convention (tests/server/test_lifecycle.py): arms that
# exercise process groups / signals skip on Windows, where CPython silently
# ignores start_new_session and os.getpgrp does not exist.
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="process-group arm: POSIX only"
)

# The literal great-docs 0.17.0 banner shape (design §2.3's local 2m20s run).
# Counts and the output path are synthetic; the marker strings the runner
# matches on are the tool's own fixed text.
BANNER_OK_HEAD = "[OK] Build complete — 21/19 steps (9 skipped, 1 warning)"
BANNER_TOTAL_TIME = "Total time: 2m 20.1s"
BANNER_SITE_READY = "Site ready (1 warning) → /scratch/sdk-worktree/great-docs/_site"
BANNER_FAIL = "[FAIL] Build failed — 2/19 steps failed"

GRANDCHILD = "import time; time.sleep(3600)"

# The synthetic CI shape: banner first, then never exit, holding two sleeping
# grandchildren (the run-38758274375 orphan tree). argv[1] receives a path the
# child writes its process-group id to, so the arms can probe the group after
# run() returns.
_CHILD_OK_HANG = f"""
import os, subprocess, sys, time
for _ in range(2):
    subprocess.Popen([sys.executable, "-c", {GRANDCHILD!r}])
for line in ({BANNER_OK_HEAD!r}, {BANNER_TOTAL_TIME!r}, {BANNER_SITE_READY!r}):
    sys.stdout.write(line + "\\n")
sys.stdout.flush()
open(sys.argv[1], "w").write(str(os.getpgrp()))
time.sleep(3600)
"""

_CHILD_FAIL_HANG = f"""
import os, subprocess, sys, time
subprocess.Popen([sys.executable, "-c", {GRANDCHILD!r}])
sys.stdout.write({BANNER_FAIL!r} + "\\n")
sys.stdout.flush()
open(sys.argv[1], "w").write(str(os.getpgrp()))
time.sleep(3600)
"""

_CHILD_CLEAN_EXIT = f"""
import sys
for line in ({BANNER_OK_HEAD!r}, {BANNER_TOTAL_TIME!r}, {BANNER_SITE_READY!r}):
    sys.stdout.write(line + "\\n")
sys.stdout.flush()
"""

_CHILD_EXIT_SEVEN = """
import sys
sys.stdout.write("partial output before failure\\n")
sys.exit(7)
"""

_CHILD_NO_BANNER_HANG = f"""
import os, subprocess, sys, time
for _ in range(2):
    subprocess.Popen([sys.executable, "-c", {GRANDCHILD!r}])
sys.stdout.write("step 12/19 rendering reference pages\\n")
sys.stdout.flush()
open(sys.argv[1], "w").write(str(os.getpgrp()))
time.sleep(3600)
"""

_CHILD_SITE_READY_ONLY = f"""
import os, sys, time
sys.stdout.write({BANNER_SITE_READY!r} + "\\n")
sys.stdout.flush()
open(sys.argv[1], "w").write(str(os.getpgrp()))
time.sleep(3600)
"""

# The --from-repo wrapper's own completion line (great_docs/core.py:16736 in
# 0.17.0): printed after the built site is copied into --output-dir, before
# the finally-rmtree of the temp clone.
SITE_BUILT_LINE = "Site built successfully"

# A faithful --from-repo child: the INNER build's banner first, then 32 files
# of copy work in four batches (the copytree tail the outer process still has
# ahead of it when the inner banner lands), then the OUTER completion line,
# then the CI wedge (never exits, two grandchildren held).
_CHILD_ISO_FAITHFUL = f"""
import os, subprocess, sys, time
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for _ in range(2):
    subprocess.Popen([sys.executable, "-c", {GRANDCHILD!r}])
for line in ({BANNER_OK_HEAD!r}, {BANNER_TOTAL_TIME!r}, {BANNER_SITE_READY!r}):
    sys.stdout.write(line + "\\n")
sys.stdout.flush()
open(sys.argv[2], "w").write(str(os.getpgrp()))
for batch in range(4):
    for i in range(8):
        open(os.path.join(out, f"page-{{batch}}-{{i}}.html"), "w").write("<html>x</html>\\n")
    sys.stdout.write(f"copied batch {{batch}}\\n")
    sys.stdout.flush()
    time.sleep(0.5)
sys.stdout.write({SITE_BUILT_LINE!r} + "\\n")
sys.stdout.flush()
time.sleep(3600)
"""


def _load() -> Any:
    """Load the script once per session (tests/test_release_cut.py's pattern)."""
    existing = sys.modules.get("assemble_docs_site_under_test")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("assemble_docs_site_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _group_is_empty(pgid_file: Path, *, drain_s: float = 5.0) -> bool:
    """True when no member remains in the child's process group. killpg(0)
    answers ProcessLookupError for an empty group — but a group holding only
    freshly orphaned zombies can answer PermissionError on macOS until
    re-adoption reaps them (observed under pytest-xdist load), so drain that
    window (bounded) before concluding members survive."""
    pgid = int(pgid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + drain_s
    while True:
        try:
            os.killpg(pgid, 0)
            return False  # signalable members: alive
        except ProcessLookupError:
            return True
        except PermissionError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


@POSIX_ONLY
def test_ok_banner_hang_ends_at_the_banner_and_reclaims_the_group(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance §8 item 1: the banner-then-hang child (holding two
    grandchildren) ends via E2 — success within grace+5s, the disclosure log
    present, the banner forwarded live, and the child's whole process group
    empty afterwards (no orphans). Three trials, all passing."""
    mod = _load()
    for trial in range(3):
        pgid_file = tmp_path / f"ok-hang-pgid-{trial}"
        started = time.monotonic()
        out = mod.run(
            [sys.executable, "-c", _CHILD_OK_HANG, str(pgid_file)],
            cwd=tmp_path,
            done_marker=True,
            grace=3.0,
            timeout=60.0,
        )
        elapsed = time.monotonic() - started
        assert out == "", f"trial {trial}: the guarded path must return ''"
        assert pgid_file.exists(), f"trial {trial}: the child never wrote its pgid"
        assert _group_is_empty(pgid_file), f"trial {trial}: orphans survived reclamation"
        assert elapsed < 8.0, f"trial {trial}: reclaim took {elapsed:.1f}s (grace is 3s)"
        captured = capsys.readouterr()
        assert BANNER_OK_HEAD in captured.out, f"trial {trial}: banner not forwarded live"
        assert "reclaimed after" in captured.out, f"trial {trial}: no E2 disclosure log"


def test_clean_exit_child_pays_no_grace_and_honors_the_real_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """E1 — the only case seen locally (design §2.3): a child that exits on
    its own returns immediately, no grace wait, no reclamation log; a
    non-zero exit fails loudly with the REAL code (output was already
    forwarded live, so there is nothing left to reprint)."""
    mod = _load()
    started = time.monotonic()
    out = mod.run(
        [sys.executable, "-c", _CHILD_CLEAN_EXIT],
        cwd=tmp_path,
        done_marker=True,
        grace=30.0,  # a grace wait here would cost 30s and prove the ending wrong
        timeout=60.0,
    )
    elapsed = time.monotonic() - started
    assert out == ""
    assert "reclaimed" not in capsys.readouterr().out
    assert elapsed < 5.0, f"E1 took {elapsed:.1f}s — a clean exit must not pay grace"
    with pytest.raises(SystemExit, match=r"command failed \(7\)"):
        mod.run(
            [sys.executable, "-c", _CHILD_EXIT_SEVEN],
            cwd=tmp_path,
            done_marker=True,
            grace=30.0,
            timeout=60.0,
        )


@POSIX_ONLY
def test_fail_banner_hang_fails_loudly_naming_the_command(tmp_path: Path) -> None:
    """Acceptance §8 item 3: the FAIL banner outranks everything (checked
    first) — the run reclaims the group, then raises SystemExit naming the
    command; no exit code exists to report, and the message says 'banner'
    rather than fabricating one."""
    mod = _load()
    pgid_file = tmp_path / "fail-hang-pgid"
    with pytest.raises(SystemExit, match=r"command failed \(banner\)") as excinfo:
        mod.run(
            [sys.executable, "-c", _CHILD_FAIL_HANG, str(pgid_file)],
            cwd=tmp_path,
            done_marker=True,
            grace=3.0,
            timeout=60.0,
        )
    assert sys.executable in str(excinfo.value), "the failure must name the command"
    assert _group_is_empty(pgid_file), "E3 must reclaim the group too"


@POSIX_ONLY
def test_no_marker_timeout_now_reclaims_the_group_too(tmp_path: Path) -> None:
    """E4 backstop: a mid-build wedge with NO banner rides the outer timeout —
    which today (issue #475's shape) kills only the direct child and leaks the
    grandchildren to the runner. The guarded path reclaims the whole group
    before the named-timeout SystemExit."""
    mod = _load()
    pgid_file = tmp_path / "e4-pgid"
    with pytest.raises(SystemExit, match=r"command timed out after 2s"):
        mod.run(
            [sys.executable, "-c", _CHILD_NO_BANNER_HANG, str(pgid_file)],
            cwd=tmp_path,
            done_marker=True,
            grace=3.0,
            timeout=2.0,
        )
    assert _group_is_empty(pgid_file), "E4 must reclaim the group, not just the child"


@POSIX_ONLY
def test_a_lone_site_ready_line_does_not_complete_the_marker(tmp_path: Path) -> None:
    """R3: the OK marker is a CONJUNCTION — "[OK] Build complete" and a
    following "Site ready" line. A child emitting only the second half (any
    build output quoting the banner's last line) must NOT end the step early:
    with grace below the timeout there is no E2, only the E4 bound."""
    mod = _load()
    pgid_file = tmp_path / "site-only-pgid"
    with pytest.raises(SystemExit, match=r"command timed out after 4s"):
        mod.run(
            [sys.executable, "-c", _CHILD_SITE_READY_ONLY, str(pgid_file)],
            cwd=tmp_path,
            done_marker=True,
            grace=1.5,  # a false-positive marker would end here first, via E2
            timeout=4.0,
        )
    assert _group_is_empty(pgid_file)


@POSIX_ONLY
def test_isolated_marker_waits_for_the_outer_completion_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F1 (fold wave): the --from-repo call site's marker is the OUTER
    process's own completion line — "Site built successfully", printed after
    the built site is copied into --output-dir — never the inner build's
    banner, which lands while the outer still has the copy (and the temp
    clone cleanup) ahead of it. A faithful child (inner banner, 32 files of
    copy work in four batches, outer line, then the wedge) must return with
    EVERY file present: a reclaim at the inner banner is silent truncation
    reported as success — lane A measured 1337/3000 files with index.html
    present, which bucket_source() and the existence-only verify_tree()
    would both pass. Real-run confirmation: the captured 0.17.0 --from-repo
    tail is inner banner box, "Copying built site to <out>...",
    "Site built successfully: <out>"."""
    mod = _load()
    out_dir = tmp_path / "iso-out"
    pgid_file = tmp_path / "iso-pgid"
    out = mod.run(
        [sys.executable, "-c", _CHILD_ISO_FAITHFUL, str(out_dir), str(pgid_file)],
        cwd=tmp_path,
        done_marker="isolated",
        grace=1.0,  # below the ~2s copy tail: an inner-banner match fires mid-copy
        timeout=60.0,
    )
    assert out == ""
    copied = sorted(out_dir.glob("page-*.html"))
    assert len(copied) == 32, (
        f"truncated copy reported as success: {len(copied)}/32 files at return"
    )
    captured = capsys.readouterr().out
    assert captured.index("Site built successfully") < captured.index(
        "reclaimed after"
    ), "the reclaim must follow the outer completion line, not the inner banner"
    assert _group_is_empty(pgid_file)


def test_reclaim_refuses_loudly_on_a_non_posix_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2 (fold wave): CPython on Windows silently ignores start_new_session
    and has no process groups to reclaim, so the guard cannot do its work
    there — _reclaim_group must refuse loudly with the platform named, never
    silently run unprotected. The suite's process-group arms skip on win32;
    this arm runs everywhere, pinning the refusal itself (Build Docs is
    ubuntu-only — .github/workflows/docs.yml)."""
    mod = _load()
    monkeypatch.setattr(sys, "platform", "win32")

    class _Stub:
        pid = -1

        def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
            raise AssertionError("the guard must refuse before touching the process")

    with pytest.raises(SystemExit, match=r"unsupported on win32"):
        mod._reclaim_group(_Stub())


def test_marker_regexes_pin_the_literal_0170_banner() -> None:
    """Acceptance §8 / risk R1 tripwire: the marker regexes match the literal
    0.17.0 banner text captured in the design (§2.3). If a great-docs pin bump
    changes the banner, this arm reddens first — the workflow's pin comment
    and the design §8 reopen trigger own the re-derivation."""
    mod = _load()
    assert mod.OK_BANNER_HEAD_RE.search(BANNER_OK_HEAD)
    assert mod.SITE_READY_RE.search(BANNER_SITE_READY)
    assert mod.FAIL_BANNER_RE.search(BANNER_FAIL)
