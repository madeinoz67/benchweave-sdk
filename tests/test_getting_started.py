"""The getting-started page is executable, registered and literal-free (issue #347 WS4).

``user_guide/getting-started.qmd`` is the R-6 surface: a first-timer reaches a
first check-pass from this page alone. This module makes that claim falsifiable
in CI. ``tests/test_guide_serial_host.py`` executes the guide's Python example
precisely so "the example cannot drift"; this module is its shell cousin: every
fenced ``sh`` block of the page is extracted in document order and run as ONE
sequence, with exactly two declared translations between the page's
first-timer world and CI's tree:

- **T1 — the install line.** ``uv pip install 'benchweave-sdk[scaffold]'``
  becomes a direct-reference install of the locally built wheel with the same
  extra set. The substitution must match exactly once; a reworded install line
  reddens with ``getting_started_install_line_not_found:`` — the page and the
  translation move together or the lane says so.
- **T2 — activation lines.** The page's activation forms are not spawned. The
  harness applies the two effects activation itself has: ``VIRTUAL_ENV`` set,
  and the venv's ``bin``/``Scripts`` directory prepended to ``PATH``.

Everything else runs verbatim: each line is shlex-split and run with
``subprocess.run(shell=False)``. Comment and blank lines, and the two
directory-state builtins the page teaches (``cd``, ``mkdir`` — no shell exists
in the harness to run them), are recognized line classes, not translations: no
command is reworded. A line the harness does not recognize aborts with
``getting_started_unrecognized_line:`` — nothing is silently skipped, because
a doc the harness quietly half-runs would be a worse lie than unrun docs.

``preview-ui`` is verified, not executed: it serves until interrupted by
design. Its command — and every other ``benchweave-sdk`` mention across the
four first-timer pages — is registration-checked against the click group at
test time, and every ``--flag`` cited with a mention must exist on that
subcommand (the WS3 R-5b rule, reused).

The four pages' prose (everything outside executable ``sh`` blocks) and the
README's added diff lines must carry zero bare semver literals, so a
per-release docs bucket cannot ship a page naming a version that aged out.
The one literal that must live inside a command — the ``--firmware`` value the
synthetic descriptor declares — is pinned against the template descriptor's
``supported_firmware`` list instead.

Planted-violation arms, permanent on every push: a fake subcommand, a bogus
flag and a wrong path, each doctored into a copy of the page and each REQUIRED
to redden; plus the fold's arms — an unrecognized-line arm (the design's
abort demo, made permanent), a registration arm for the citation check, a
fence-census arm (A-F1: a ```console re-fence left every test green), a
non-canonical-install arm (A-F2: an unquoted variant ran verbatim against
PyPI), a shell-operator arm (A-F5: `|| true` must abort, not run with the
guard dropped), and an environment arm (A-F3: an SDK line before the page's
own install rode the runner's venv through a green sequence). A checker
that passes a planted violation is itself broken (the ``test_registry_census``
planted-command pattern, and WS3's R-5c).

What this module does NOT catch: the ASD-STE100 register of the prose, and
whether a "you should see" quote matches the wording of a command's output —
only exit codes, JSON key shapes and value-free prefixes are asserted, so
passing tests never depend on content churn.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from benchweave_sdk.cli import cli

REPO = Path(__file__).resolve().parents[1]
GUIDE_DIR = REPO / "user_guide"
PAGE = GUIDE_DIR / "getting-started.qmd"
PAGES = (
    PAGE,
    GUIDE_DIR / "which-checkout.qmd",
    GUIDE_DIR / "glossary.qmd",
    GUIDE_DIR / "troubleshooting.qmd",
)
README = REPO / "README.md"
GREAT_DOCS_YML = REPO / "great-docs.yml"
CITED_GETTING_STARTED = (
    "https://madeinoz67.github.io/benchweave-sdk/docs/user-guide/getting-started.html"
)
TEMPLATE_DESCRIPTOR = REPO / "template" / "src" / "{{ package_name }}" / "descriptor.json.jinja"

# A-F1 (fold): only sh blocks execute and only sh/text blocks feed the
# registration scan, so a re-fence to any other language (bash, console, ...)
# silently removes a block from BOTH checks. Measured live: a ```console
# re-fence on which-checkout.qmd left every test green. The census is pinned
# per page; re-fencing is a shape change that updates it deliberately.
EXPECTED_FENCES = {
    "getting-started.qmd": {"sh": 11, "text": 6},
    "which-checkout.qmd": {"sh": 3},
    "glossary.qmd": {},
    "troubleshooting.qmd": {"sh": 3},
}

INSTALL_LINE = "uv pip install 'benchweave-sdk[scaffold]'"
ACTIVATION_LINES = (
    "source .venv/bin/activate",
    r".venv\Scripts\Activate.ps1",
    r".venv\Scripts\activate.bat",
)
MIN_BLOCKS = 8
COMMAND_TIMEOUT_S = 600

# The same bare-semver shape scripts/count_version_literals.py calls Pattern B.
SEMVER = re.compile(r"\d+\.\d+\.\d+")
SH_FENCE = re.compile(r"```sh\n(.*?)```", re.S)
ANY_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.S)
# A CLI mention: a backticked span, or a fenced-block line, naming the binary.
# ``--version``/``--help`` are bare-group options, not subcommands; they are
# admitted as exactly those two names so a page that only cites them (the
# which-checkout page) still has a checkable denominator.
COMMAND_IN_SPAN = re.compile(r"benchweave-sdk\s+([a-z][a-z0-9-]*|--version|--help)")
COMMAND_LINE = re.compile(r"^\s*(?:\$\s+)?benchweave-sdk\s+([a-z][a-z0-9-]*|--version|--help)")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*(?:=[^\s\\]+)?)")


# --- extraction ---------------------------------------------------------------


def logical_lines(block: str) -> list[str]:
    """Continuation lines joined, comment and blank lines dropped."""
    lines: list[str] = []
    pending = ""
    for raw in block.splitlines():
        text = f"{pending} {raw.strip()}".strip() if pending else raw.strip()
        if text.endswith("\\"):
            pending = text[:-1]
            continue
        pending = ""
        if not text or text.startswith("#"):
            continue
        lines.append(text)
    if pending:
        lines.append(pending)
    return lines


def extract_sh_blocks(text: str) -> list[list[str]]:
    """Every fenced ``sh`` block of the page, in document order."""
    return [logical_lines(block) for block in SH_FENCE.findall(text)]


def sections(text: str) -> list[str]:
    """The ``##``-level section titles, in order."""
    return [part.splitlines()[0].strip() for part in re.split(r"^## ", text, flags=re.M)[1:]]


# --- execution ----------------------------------------------------------------


@dataclass
class Record:
    line: str
    proc: subprocess.CompletedProcess[str]
    cwd: Path
    venv: Path | None


def _base_env() -> dict[str, str]:
    """The child environment every page command runs in (see the call-site
    comment for why the two runner markers are stripped)."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
    }


def _apply_activation(cwd: Path, env: dict[str, str]) -> Path | None:
    """T2: the two effects an activation line itself has, applied natively.

    Sets VIRTUAL_ENV to the cwd's `.venv` and prepends the venv's scripts
    directory (`bin` on POSIX, `Scripts` on Windows — whichever exists) with
    the platform's PATH separator. Returns the venv, or None when there is
    no `.venv` at the cwd (a named failure upstream).
    """
    candidate = cwd / ".venv"
    if not candidate.is_dir():
        return None
    env["VIRTUAL_ENV"] = str(candidate)
    for name in ("bin", "Scripts"):
        scripts = candidate / name
        if scripts.is_dir():
            env["PATH"] = os.pathsep.join([str(scripts), env.get("PATH", "")])
            break
    return candidate


def execute_sequence(
    blocks: list[list[str]], scratch: Path, wheel: Path
) -> tuple[list[str], list[Record]]:
    """Run the page's blocks as one sequence; abort at the first failure.

    Returns ``(failures, records)``. An empty failure list with the page's
    full block count is a green run of the page exactly as written.
    """
    failures: list[str] = []
    records: list[Record] = []
    cwd = scratch
    # VIRTUAL_ENV is the page's own variable (T2 sets it at the activation
    # line); UV_PROJECT_ENVIRONMENT must not leak either — a runner convention
    # of `venv` would make the page's uv commands create a project-local
    # venv/ inside the scaffolded plugin, which then rides into uv build's
    # artifacts (fold B-F2's poison, kept out of the page's world).
    env = _base_env()
    venv: Path | None = None
    translated_installs = 0

    for block in blocks:
        for line in block:
            if line in ACTIVATION_LINES:
                activated = _apply_activation(cwd, env)
                if activated is None:
                    failures.append(
                        f"getting_started_activation_without_venv: {line} at {cwd}"
                    )
                    return failures, records
                venv = activated
                continue

            parts = shlex.split(line)
            if not parts:
                failures.append(f"getting_started_unrecognized_line: {line}")
                return failures, records
            head = parts[0]

            # A-F5 (fold): a shell operator the harness will not interpret
            # must abort by name. Running the first command with the guard
            # silently dropped is not execution of the page.
            if any(
                part in {"||", "&&", ";", "|"} or part.startswith((">", "<"))
                for part in parts
            ):
                failures.append(
                    f"getting_started_unrecognized_line: {line} "
                    "(shell operator the harness refuses)"
                )
                return failures, records

            # Directory-state builtins: no shell exists here to run them, so
            # the harness applies them natively. Not a translation — the
            # command's effect (change directory / make directory) is exactly
            # what the page teaches, applied verbatim.
            if head == "cd":
                if len(parts) != 2:
                    failures.append(f"getting_started_unrecognized_line: {line}")
                    return failures, records
                target = Path(parts[1])
                cwd = Path(os.path.normpath(target if target.is_absolute() else cwd / target))
                continue
            if head == "mkdir":
                if len(parts) != 2:
                    failures.append(f"getting_started_unrecognized_line: {line}")
                    return failures, records
                (cwd / parts[1]).mkdir(parents=True, exist_ok=True)
                continue

            # A-F2 (fold): any SDK-naming uv pip install that is not the
            # canonical line aborts. A differently-worded variant ran
            # verbatim against PyPI inside the sequence and every test stayed
            # green — the refusal closes that hole before anything installs.
            if (
                head == "uv"
                and "benchweave-sdk" in line
                and {"pip", "install"} <= set(parts)
                and line != INSTALL_LINE
            ):
                failures.append(
                    f"getting_started_install_line_not_canonical: {line!r} installs "
                    f"the SDK but is not the canonical form {INSTALL_LINE!r}"
                )
                return failures, records

            # T1 — the one declared command substitution.
            if line == INSTALL_LINE:
                if venv is None:
                    failures.append(
                        f"getting_started_install_before_activation: {line} at {cwd}"
                    )
                    return failures, records
                parts = [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(venv),
                    f"benchweave-sdk[scaffold] @ {wheel.as_uri()}",
                ]
                translated_installs += 1

            # A-F3 (fold): benchweave-sdk and pytest must come from the
            # page's own environment. Before activation there is none, and a
            # resolution from the runner's venv let a broken install pass
            # green (measured: an inserted pre-activation --version rode the
            # runner's environment through an all-green sequence).
            if head in ("benchweave-sdk", "pytest"):
                if venv is None:
                    failures.append(
                        f"getting_started_environment_not_ready: {line} runs "
                        "before the page's Step 0/1 environment exists"
                    )
                    return failures, records
                resolved_head = shutil.which(head, path=env.get("PATH"))
                if resolved_head is None or not resolved_head.startswith(str(venv)):
                    failures.append(
                        f"getting_started_wrong_environment: {line} resolved "
                        f"outside the page's environment ({resolved_head})"
                    )
                    return failures, records

            resolved_path = shutil.which(head, path=env.get("PATH"))
            if resolved_path is None:
                failures.append(
                    f"getting_started_unrecognized_line: {line} "
                    f"(no executable named {head!r} resolves)"
                )
                return failures, records
            # PR #103's root cause: on Windows, CreateProcess resolves a BARE
            # executable name against the PARENT's PATH, not the child env's —
            # `pytest` launched the runner's venv (its plugins line named anyio
            # and benchweave-ui-html, which only the runner's --extra server
            # environment installs) while the page's venv held the editable
            # plugin. Launch every command by the absolute path the gate just
            # verified, so the launch and the gate can never disagree.
            parts = [resolved_path, *parts[1:]]
            try:
                # argv list, shell=False by design; every part came from a
                # verbatim page line or one of the two declared translations.
                proc = subprocess.run(
                    parts,
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=COMMAND_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired:
                failures.append(
                    f"getting_started_command_failed: {line} "
                    f"(timeout after {COMMAND_TIMEOUT_S}s)"
                )
                return failures, records
            records.append(Record(line=line, proc=proc, cwd=cwd, venv=venv))
            if proc.returncode != 0:
                output = (proc.stdout + proc.stderr).strip().splitlines()
                # A collection error's traceback sits ABOVE the summary tail;
                # a one-line window hid the Windows lane's actual ImportError
                # (PR #103) — keep enough context to read the cause on the
                # next run instead of guessing across CI cycles.
                detail = "\n".join(output[-40:]) if output else "(no output)"
                failures.append(
                    f"getting_started_command_failed: {line} "
                    f"(exit {proc.returncode}):\n{detail}"
                )
                return failures, records

    if translated_installs == 0:
        failures.append(
            "getting_started_install_line_not_found: the page no longer carries "
            f"{INSTALL_LINE!r} verbatim; T1 and the page must move together"
        )
    elif translated_installs > 1:
        failures.append(
            f"getting_started_install_line_duplicated: matched {translated_installs} "
            "times; the install line must appear exactly once"
        )
    return failures, records


def _import_probes(record: Record) -> list[str]:
    """Failure-path diagnostics, not page commands: when pytest cannot even
    summarize, run the venv's own python in the same cwd and import exactly
    what the generated test module imports at collection time. The stderr
    names the missing module directly, on any OS — PR #103's Windows
    collection error was undiagnosable because the harness had eaten the
    traceback; these probes make the next failure self-describing."""
    if record.venv is None:
        return []
    python: Path | None = None
    for scripts in ("bin", "Scripts"):
        for name in ("python", "python.exe"):
            if (record.venv / scripts / name).is_file():
                python = record.venv / scripts / name
                break
        if python is not None:
            break
    if python is None:
        return ["getting_started_probe: no python found in the page's venv"]
    modules = ["benchweave_sdk.testing", "benchweave_sdk.validation"]
    sources = sorted((record.cwd / "src").iterdir()) if (record.cwd / "src").is_dir() else []
    if sources:
        modules.append(f"{sources[0].name}.adapter")
    findings: list[str] = []
    for module in modules:
        probe = subprocess.run(
            [str(python), "-c", f"import {module}"],
            cwd=record.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
        if probe.returncode != 0:
            tail = probe.stderr.strip().splitlines()[-1:] or ["(no output)"]
            findings.append(
                f"getting_started_probe: the venv python cannot import {module}: "
                f"{tail[0]}"
            )
    return findings


def content_failures(records: list[Record]) -> list[str]:
    """The value-free output assertions over the recorded sequence."""
    failures: list[str] = []
    pytest_run = next((record for record in records if record.line == "pytest"), None)
    if pytest_run is None:
        failures.append("getting_started_pytest_missing: the page no longer runs pytest")
    else:
        output = pytest_run.proc.stdout + pytest_run.proc.stderr
        summary = re.search(r"(\d+) passed", output)
        if summary is None:
            failures.append(
                "getting_started_pytest_summary: no '<n> passed' in the pytest output; "
                f"tail was {output[-1500:]!r}"
            )
            failures += _import_probes(pytest_run)
        elif int(summary.group(1)) < 1:
            failures.append("getting_started_pytest_summary: zero tests passed")

    inventory = next(
        (record for record in records if record.line == "benchweave-sdk inventory dist/"),
        None,
    )
    if inventory is None:
        failures.append(
            "getting_started_inventory_missing: the page no longer runs 'inventory dist/'"
        )
    else:
        rows: list[dict[str, object]] = []
        try:
            parsed = json.loads(inventory.proc.stdout)
        except json.JSONDecodeError:
            failures.append("getting_started_inventory_json: inventory stdout is not JSON")
        else:
            if isinstance(parsed, list):
                rows = parsed
            if len(rows) < 2:
                failures.append(
                    "getting_started_inventory_rows: fewer than two rows in the inventory"
                )
            for row in rows:
                if not {"path", "bytes", "sha256"} <= set(row):
                    failures.append(
                        "getting_started_inventory_keys: an inventory row lacks "
                        "path/bytes/sha256"
                    )
                    break

    doctor = next(
        (record for record in records if record.line == "benchweave-sdk doctor"), None
    )
    if doctor is None:
        failures.append("getting_started_doctor_missing: the page no longer runs doctor")
    elif "Scaffold version matches the installed SDK:" not in doctor.proc.stdout:
        failures.append(
            "getting_started_doctor_output: doctor no longer reports the match prefix"
        )
    return failures


# --- fixtures -------------------------------------------------------------------


@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The wheel CI installs in place of the PyPI install the page teaches."""
    out = tmp_path_factory.mktemp("ws4-wheel")
    subprocess.run(
        ["uv", "build", "--out-dir", str(out)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=COMMAND_TIMEOUT_S,
    )
    built = sorted(out.glob("*.whl"))
    assert len(built) == 1, f"expected exactly one wheel, found {[path.name for path in built]}"
    return built[0]


def test_launched_commands_use_the_resolved_absolute_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #103's root cause, pinned locally: on Windows, CreateProcess resolves
    a bare executable name against the PARENT's PATH, not the child
    environment's — so `pytest` launched the RUNNER's venv (its session
    header named the plugins anyio and benchweave-ui-html, which only the
    runner's `--extra server` environment installs) while the page's venv
    held the editable plugin. The harness must launch every command by its
    shutil.which-resolved ABSOLUTE path, so the launch lands where the A-F3
    gate already verified."""
    scripts = tmp_path / ".venv" / "bin"
    scripts.mkdir(parents=True)
    stub = scripts / "benchweave-sdk"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    launched: list[str] = []
    real_run = subprocess.run

    def spying_run(parts: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        launched.append(parts[0])
        return real_run(parts, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", spying_run)
    page = "```sh\nsource .venv/bin/activate\nbenchweave-sdk --version\n```\n"
    _failures, _records = execute_sequence(extract_sh_blocks(page), tmp_path, Path("/unused"))
    assert launched and launched[0] == str(stub), (
        "getting_started_launch: commands must launch by the resolved absolute "
        "path; a bare name resolves against the PARENT's PATH on Windows, which "
        "is how the runner's pytest answered for the page's (PR #103)"
    )


# --- T2's environment emulation, unit-pinned cross-OS ----------------------------------


def test_the_child_env_strips_the_runner_environment_markers() -> None:
    """The page's world starts clean: the runner's VIRTUAL_ENV and
    UV_PROJECT_ENVIRONMENT must not leak into any page command."""
    saved = {key: os.environ.get(key) for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
    try:
        os.environ["VIRTUAL_ENV"] = "/definitely/not/the/pages"
        os.environ["UV_PROJECT_ENVIRONMENT"] = "venv"
        env = _base_env()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    assert "VIRTUAL_ENV" not in env
    assert "UV_PROJECT_ENVIRONMENT" not in env


def test_activation_prepends_the_windows_shaped_scripts_dir(tmp_path: Path) -> None:
    """PR #103: the Windows lane is the only place the `Scripts` branch runs
    against a real venv. This pins the emulation's shape locally: a venv laid
    out the Windows way (Scripts/) activates with Scripts prepended using
    the platform separator and VIRTUAL_ENV set; a POSIX-shaped venv (bin/)
    activates with bin; a missing venv returns None for the named failure."""
    windows_like = tmp_path / "w" / ".venv"
    (windows_like / "Scripts").mkdir(parents=True)
    env = {"PATH": "/base"}
    assert _apply_activation(tmp_path / "w", env) == windows_like
    assert env["VIRTUAL_ENV"] == str(windows_like)
    assert env["PATH"].split(os.pathsep)[0] == str(windows_like / "Scripts")

    posix_like = tmp_path / "p" / ".venv"
    (posix_like / "bin").mkdir(parents=True)
    env = {"PATH": "/base"}
    assert _apply_activation(tmp_path / "p", env) == posix_like
    assert env["PATH"].split(os.pathsep)[0] == str(posix_like / "bin")

    assert _apply_activation(tmp_path / "empty", {"PATH": "/base"}) is None


# --- the page's shape ------------------------------------------------------------


def test_the_page_carries_at_least_eight_sh_blocks() -> None:
    blocks = extract_sh_blocks(PAGE.read_text(encoding="utf-8"))
    assert len(blocks) >= MIN_BLOCKS, (
        f"getting_started_block_floor: {len(blocks)} sh blocks < {MIN_BLOCKS}; "
        "the page's shape is part of the contract — a reformatted-away block "
        "must redden with this name, not shrink the run"
    )


def test_every_step_section_keeps_its_commands() -> None:
    text = PAGE.read_text(encoding="utf-8")
    titles = sections(text)
    steps = {title.split(".")[0] for title in titles if title.startswith("Step ")}
    assert steps == {f"Step {number}" for number in range(8)}, (
        f"getting_started_step_empty: expected steps 0-7, found {sorted(steps)}"
    )
    bodies = re.split(r"^## ", text, flags=re.M)[1:]
    for title, body in zip(titles, bodies, strict=True):
        if title.startswith("Step 7"):
            continue  # the where-next pointer section is prose by design
        assert SH_FENCE.search(body), (
            f"getting_started_step_empty: section {title!r} lost its sh block(s)"
        )


def fence_census(text: str) -> dict[str, int]:
    """One entry per fenced block, keyed by its language tag."""
    census: dict[str, int] = {}
    for language, _body in ANY_FENCE.findall(text):
        key = language or "(none)"
        census[key] = census.get(key, 0) + 1
    return census


def census_problems(named: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for name, text in named.items():
        census = fence_census(text)
        if census != EXPECTED_FENCES[name]:
            problems.append(
                f"getting_started_fence_census: {name}: {census} != "
                f"{EXPECTED_FENCES[name]} — a re-fenced block escapes the "
                "executor (sh) or the registration scan (sh/text)"
            )
    return problems


def test_the_fence_language_census_is_pinned() -> None:
    named = {page.name: page.read_text(encoding="utf-8") for page in PAGES}
    problems = census_problems(named)
    assert problems == [], "\n" + "\n".join(problems)


# --- the sequence -----------------------------------------------------------------


def test_the_page_runs_green_to_a_first_check_pass(tmp_path: Path, wheel: Path) -> None:
    blocks = extract_sh_blocks(PAGE.read_text(encoding="utf-8"))
    failures, records = execute_sequence(blocks, tmp_path, wheel)
    failures += content_failures(records)
    dist = tmp_path / "first-plugin" / "plugins" / "acme" / "model100" / "dist"
    if not list(dist.glob("*.whl")) or not list(dist.glob("*.tar.gz")):
        failures.append(
            "getting_started_build_outputs: uv build left no wheel and sdist pair under dist/"
        )
    assert failures == [], "\n" + "\n".join(failures)


# --- planted violations, permanent --------------------------------------------------


ARM_LINES = {
    "fake_subcommand": "benchweave-sdk frobnicate",
    "bogus_flag": "benchweave-sdk check --bogus-flag",
    "wrong_path": "benchweave-sdk check /no/such/path.json",
}


@pytest.mark.parametrize("line", ARM_LINES.values(), ids=ARM_LINES)
def test_a_planted_violation_reddens(tmp_path: Path, wheel: Path, line: str) -> None:
    """Each doctored copy of the page MUST fail at its first command."""
    text = PAGE.read_text(encoding="utf-8")
    doctored = f"```sh\n{line}\n```\n{text}"
    failures, _records = execute_sequence(extract_sh_blocks(doctored), tmp_path, wheel)
    assert failures, f"a planted violation passed: {line}"
    assert line in failures[0], f"{failures[0]} does not name the planted line {line!r}"


def test_an_unrecognized_line_aborts_the_sequence(tmp_path: Path, wheel: Path) -> None:
    """A shell construct the harness refuses must abort by name, not pass."""
    text = PAGE.read_text(encoding="utf-8")
    doctored = "```sh\nexport GETTING_STARTED_ARM=yes\n```\n" + text
    failures, _records = execute_sequence(extract_sh_blocks(doctored), tmp_path, wheel)
    assert failures and failures[0].startswith(
        "getting_started_unrecognized_line:"
    ), failures


# --- the fold's rows, each with the miss it closes ------------------------------------


def test_a_refenced_block_reddens_the_census() -> None:
    """A-F1's live proof: a ```console re-fence on which-checkout.qmd left
    every test green (measured, 12 passed) — the block escaped the executor
    and the registration scan. The census now reds on the same doctoring."""
    named = {page.name: page.read_text(encoding="utf-8") for page in PAGES}
    doctored = dict(named)
    doctored["which-checkout.qmd"] = named["which-checkout.qmd"].replace(
        "```sh\n", "```console\n", 1
    )
    problems = census_problems(doctored)
    assert problems and "which-checkout" in problems[0], problems


def test_a_noncanonical_install_line_reddens(tmp_path: Path, wheel: Path) -> None:
    """A-F2's live proof: an unquoted `uv pip install benchweave-sdk` beside
    the canonical line ran verbatim against PyPI inside the sequence and the
    module stayed green (measured, 12 passed). The refusal aborts before any
    install runs."""
    text = PAGE.read_text(encoding="utf-8")
    doctored = "```sh\nuv pip install benchweave-sdk\n```\n" + text
    failures, _records = execute_sequence(extract_sh_blocks(doctored), tmp_path, wheel)
    assert failures and failures[0].startswith(
        "getting_started_install_line_not_canonical:"
    ), failures


def test_a_shell_operator_line_aborts(tmp_path: Path, wheel: Path) -> None:
    """A-F5: `cmd || true` must abort as a shell construct, not run with the
    guard silently dropped."""
    text = PAGE.read_text(encoding="utf-8")
    doctored = "```sh\nbenchweave-sdk doctor || true\n```\n" + text
    failures, _records = execute_sequence(extract_sh_blocks(doctored), tmp_path, wheel)
    assert failures and failures[0].startswith(
        "getting_started_unrecognized_line:"
    ), failures


def test_an_sdk_use_outside_the_page_environment_reddens(
    tmp_path: Path, wheel: Path
) -> None:
    """A-F3's live proof: a benchweave-sdk line before Step 0/1 resolved from
    the runner's own venv, exited 0, and the whole sequence stayed green
    (that is the ride the row names). It must abort before running."""
    text = PAGE.read_text(encoding="utf-8")
    doctored = "```sh\nbenchweave-sdk --version\n```\n" + text
    failures, _records = execute_sequence(extract_sh_blocks(doctored), tmp_path, wheel)
    assert failures and failures[0].startswith(
        (
            "getting_started_environment_not_ready:",
            "getting_started_wrong_environment:",
        )
    ), failures


# --- registration of every CLI mention ----------------------------------------------


def registered_subcommands() -> set[str]:
    return set(cli.commands)


def command_citations(text: str) -> list[tuple[str, list[str]]]:
    """(subcommand, cited flags) for every CLI mention: backticked spans,
    fenced sh/text lines, and — since the fold's A-F4 — unbackticked prose
    (flags are not collected from bare prose; spans and fences stay the flag
    surfaces)."""
    found: list[tuple[str, list[str]]] = []
    for span in re.findall(r"`([^`\n]+)`", text):
        match = COMMAND_IN_SPAN.search(span)
        if match:
            flags = FLAG.findall(span[match.end() :])
            found.append((match.group(1), flags))
    for language, body in ANY_FENCE.findall(text):
        if language not in ("sh", "text"):
            continue
        for line in logical_lines(body):
            match = COMMAND_LINE.match(line)
            if match:
                flags = FLAG.findall(line[match.end() :])
                found.append((match.group(1), flags))
    prose = re.sub(r"`[^`\n]+`", "", ANY_FENCE.sub("", text))
    for match in re.finditer(
        r"benchweave-sdk\s+([a-z][a-z0-9-]*|--version|--help)", prose
    ):
        found.append((match.group(1), []))
    return found


def registration_problems(page: Path, text: str, commands: set[str]) -> list[str]:
    problems: list[str] = []
    for subcommand, flags in command_citations(text):
        if subcommand.startswith("--"):
            if subcommand not in ("--version", "--help"):
                problems.append(
                    f"getting_started_registration: {page.name}: "
                    f"`benchweave-sdk {subcommand}` is not a bare-group option"
                )
            continue
        if subcommand not in commands:
            problems.append(
                f"getting_started_registration: {page.name}: "
                f"`benchweave-sdk {subcommand}` is not a registered command"
            )
            continue
        # The declared option strings (``param.opts``), not ``param.name``:
        # ``new`` declares ``--package`` with the parameter name
        # ``package_name``, so the name half would false-red the real flag.
        opt_names = {
            opt.lstrip("-").replace("-", "_")
            for param in cli.commands[subcommand].params
            for opt in getattr(param, "opts", ())
        }
        for flag in flags:
            if flag.split("=")[0].lstrip("-").replace("-", "_") not in opt_names:
                problems.append(
                    f"getting_started_registration: {page.name}: "
                    f"{flag} is not a flag of `benchweave-sdk {subcommand}`"
                )
    return problems


def test_every_cli_mention_on_the_four_pages_is_registered() -> None:
    commands = registered_subcommands()
    problems: list[str] = []
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        problems += registration_problems(page, text, commands)
        assert command_citations(text), (
            f"getting_started_registration: {page.name} cites nothing the checker "
            "can verify — the check is vacuous for this page"
        )
    assert problems == [], "\n" + "\n".join(problems)


def test_a_planted_unregistered_mention_is_caught() -> None:
    text = (GUIDE_DIR / "which-checkout.qmd").read_text(encoding="utf-8")
    doctored = text + "\nRun `benchweave-sdk frobnicate` to repair the mount.\n"
    problems = registration_problems(GUIDE_DIR / "which-checkout.qmd", doctored, set(cli.commands))
    assert any("frobnicate" in problem for problem in problems), (
        "the registration check passed a planted command"
    )


def test_a_planted_unbackticked_mention_is_caught() -> None:
    """A-F4: an unbackticked prose mention must not escape the scan."""
    text = (GUIDE_DIR / "which-checkout.qmd").read_text(encoding="utf-8")
    doctored = text + "\nRun benchweave-sdk frobnicate to repair the mount.\n"
    citations = {subcommand for subcommand, _flags in command_citations(doctored)}
    assert "frobnicate" in citations, (
        "an unbackticked prose mention escaped the registration scan"
    )


# --- version literals over prose ------------------------------------------------------


def test_the_four_pages_prose_carries_no_version_literals() -> None:
    """Executable ``sh`` blocks are pinned by execution (and the firmware pin
    below); everything else — including quoted-output text blocks — must name
    no version, so a docs bucket cannot ship a page with an aged-out number."""
    problems: list[str] = []
    for page in PAGES:
        prose = SH_FENCE.sub("", page.read_text(encoding="utf-8"))
        hits = SEMVER.findall(prose)
        if hits:
            problems.append(f"getting_started_version_literal: {page.name}: {hits}")
    assert problems == [], "\n" + "\n".join(problems)


def test_the_readme_delta_carries_no_version_literals() -> None:
    proc = subprocess.run(
        ["git", "diff", "origin/main...HEAD", "--", "README.md"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, (
        "getting_started_readme_delta_unavailable: the README literal gate cannot "
        f"run (git diff failed: {proc.stderr.strip()})"
    )
    added = [
        line[1:]
        for line in proc.stdout.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    hits = [line for line in added if SEMVER.search(line)]
    assert not hits, (
        "getting_started_version_literal: README added lines carry a bare semver: "
        f"{hits!r}"
    )


def test_the_pages_firmware_value_matches_the_template_descriptor() -> None:
    """The one literal that must live in a command is pinned to its source:
    the synthetic descriptor's declared supported_firmware list (gap G12's
    provenance, made mechanical)."""
    cited = set(re.findall(r"--firmware\s+([^\s\\]+)", PAGE.read_text(encoding="utf-8")))
    assert cited, "getting_started_firmware_pin: the page no longer cites --firmware"
    template = TEMPLATE_DESCRIPTOR.read_text(encoding="utf-8")
    declared_block = re.search(r'"supported_firmware"\s*:\s*\[(.*?)\]', template, re.S)
    assert declared_block is not None, (
        "getting_started_firmware_pin: the template descriptor lost supported_firmware"
    )
    declared = set(re.findall(r'"([^"]+)"', declared_block.group(1)))
    assert cited <= declared, (
        f"getting_started_firmware_pin: the page cites --firmware {sorted(cited)}; "
        f"the template descriptor declares {sorted(declared)}"
    )


# --- the fold's static pins (pages, navigation, citations) ----------------------------


def test_the_pages_teach_one_test_path() -> None:
    """B-F2: `uv run --extra test pytest` on a UV_PROJECT_ENVIRONMENT=venv
    machine creates a project-local venv/ inside the plugin, and that tree
    rides into the build outputs. No page may TEACH that form. The G8
    symptom row still NAMES `uv run pytest` — a reader who hit it must find
    the row — but its Fix offers the activated environment only."""
    for page in PAGES:
        assert "uv run --extra test" not in page.read_text(encoding="utf-8"), (
            f"getting_started_single_path: {page.name} teaches the uv run "
            "deviation that builds a second environment inside the project"
        )
    row = (GUIDE_DIR / "troubleshooting.qmd").read_text(encoding="utf-8")
    row_body = row.split("`uv run pytest` reports a missing module", 1)[1]
    row_fix = row_body.split("**Fix.**", 1)[1].split("\n## ", 1)[0]
    assert "pytest` after `source .venv/bin/activate" in row_fix, (
        "getting_started_single_path: the G8 row's fix must offer the "
        "activated-environment path"
    )
    assert "uv run" not in row_fix, (
        "getting_started_single_path: the G8 row's fix must not offer uv run"
    )


def test_expected_output_promises_no_line_count() -> None:
    """B-F3: the CLI wraps its messages at the terminal width (measured: the
    created-message is three lines at 80 columns, one line at 120). The page
    promises the message text, never a wrap."""
    for page in PAGES:
        assert "over two lines" not in page.read_text(encoding="utf-8"), (
            f"getting_started_width_promise: {page.name} promises a "
            "terminal-width-dependent line count"
        )


def test_the_landing_flip_stays_reverted() -> None:
    """B-F1 static half: homepage: user_guide promotes the first user-guide
    page to the site root, where its relative .qmd hrefs 404 and every
    inbound citation of user-guide/getting-started.html dangles (measured:
    sixteen dead links). The recorded fallback stands; the built-tree half
    is scripts/check_docs_links.py in the docs lane."""
    yml = GREAT_DOCS_YML.read_text(encoding="utf-8")
    assert re.search(r"^homepage:\s*user_guide\s*$", yml, re.M) is None, (
        "getting_started_landing_flip: the flip measured broken when built; "
        "re-flipping requires re-proving the built-tree link check"
    )
    index = (REPO / "index.qmd").read_text(encoding="utf-8")
    assert "getting-started.qmd" in index.split("# Installation", 1)[0], (
        "getting_started_landing_flip: index.qmd must link the getting-started "
        "page above the fold (the recorded fallback's top-of-index link)"
    )


def test_inbound_citations_name_the_rendered_location() -> None:
    for source in (README, REPO / "CLAUDE.md"):
        text = source.read_text(encoding="utf-8")
        assert CITED_GETTING_STARTED in text, (
            f"getting_started_inbound_citation: {source.name} does not cite "
            f"{CITED_GETTING_STARTED}"
        )


def test_relative_links_resolve_inside_the_user_guide() -> None:
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#?]+\.qmd)\)", text):
            assert (page.parent / target).is_file(), (
                f"getting_started_page_link: {page.name} links {target}, "
                "which is not a sibling page"
            )
