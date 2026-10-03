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
to redden; plus two arms this module adds beyond the design's three — an
unrecognized-line arm proving the abort bites, and a registration arm for the
citation check. A checker that passes a planted violation is itself broken
(the ``test_registry_census`` planted-command pattern, and WS3's R-5c).

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
TEMPLATE_DESCRIPTOR = REPO / "template" / "src" / "{{ package_name }}" / "descriptor.json.jinja"

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
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    venv: Path | None = None
    translated_installs = 0

    for block in blocks:
        for line in block:
            if line in ACTIVATION_LINES:
                candidate = cwd / ".venv"
                if not candidate.is_dir():
                    failures.append(
                        f"getting_started_activation_without_venv: {line} at {cwd}"
                    )
                    return failures, records
                venv = candidate
                env["VIRTUAL_ENV"] = str(candidate)
                for name in ("bin", "Scripts"):
                    scripts = candidate / name
                    if scripts.is_dir():
                        env["PATH"] = os.pathsep.join([str(scripts), env.get("PATH", "")])
                        break
                continue

            parts = shlex.split(line)
            if not parts:
                failures.append(f"getting_started_unrecognized_line: {line}")
                return failures, records
            head = parts[0]

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

            if shutil.which(head, path=env.get("PATH")) is None:
                failures.append(
                    f"getting_started_unrecognized_line: {line} "
                    f"(no executable named {head!r} resolves)"
                )
                return failures, records
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
            records.append(Record(line=line, proc=proc))
            if proc.returncode != 0:
                output = (proc.stdout + proc.stderr).strip().splitlines()
                detail = output[-1] if output else "(no output)"
                failures.append(
                    f"getting_started_command_failed: {line} "
                    f"(exit {proc.returncode}): {detail}"
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
                f"tail was {output[-200:]!r}"
            )
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


# --- registration of every CLI mention ----------------------------------------------


def registered_subcommands() -> set[str]:
    return set(cli.commands)


def command_citations(text: str) -> list[tuple[str, list[str]]]:
    """(subcommand, cited flags) for every CLI mention, backticked or fenced."""
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
