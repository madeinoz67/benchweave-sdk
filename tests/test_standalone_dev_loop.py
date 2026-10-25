"""Issue #556 — the standalone development loop, proven from the installed SDK.

Design record: ``.claude/deep-review/2026-10-25-issue556-standalone-dev-mode.md``
(§2(a) the mechanism, §3 the developer's run, §8 the acceptance rule).

The gap this module closes: every composed-UI proof in the repository runs the
SDK from the checkout process (``tests/test_classref_acceptance.py``), and the
installed-wheel smokes in ``.github/workflows/ci.yml`` and ``publish.yml``
assert banners over the scaffold **starter** only. Nothing proved the composed
loop — ``new --with-ui`` → author the class → ``derive-ui`` → ``verify-ui`` →
served ``preview-ui`` — from a clean environment holding only the built wheel.

The lane therefore builds this repository's wheel once, installs
``<wheel>[server,scaffold]`` into a fresh venv OUTSIDE the checkout, and drives
the installed ``benchweave-sdk`` console script as a subprocess. Nothing here
imports the SDK into the test process to do the work: the commands are the
subject, and ``test_the_installed_sdk_is_the_venv_copy`` is the assertion that
the script under test is the installed copy rather than this checkout.

The fixture is the invented Meridian M-400 corpus from the #541 acceptance
record (``tests/fixtures/classref/descriptor-m400.json`` plus
``composed-burst.json``): one action composed through a plugin-local class and
one residual member. The composed control's field (``burst_count``) exists only
in the class's ``input_schema`` — the descriptor's own ``burst_mode`` action
declares an empty ``input_constraints`` — so the served control cannot come from
the descriptor, which is what makes it evidence.

What this module does NOT catch, stated so the claim does not outrun it:

* Anything gateway-side. The leg is SDK-only by the owner's disambiguation;
  the gateway mirror is a separate track.
* Any transport but the scripted mock. ``preview-ui`` pins ``transport="mock"``
  by design (PRD 12 R-9); real-hardware serving is out of this lane's reach.
* Visual correctness. The page assertions are the §E.1 component census and the
  loader's own banner wordings — a control can be present, derived and
  mis-styled and every arm here stays green.
* The spawned-serve arms are skipped on Windows (the skip reason names the
  coverage that remains). The non-spawn arms — install, scaffold, derive,
  verify, ledger — run on all three OSes.
* The pin's authoring friction: until ``pin-class`` lands, the pin row and its
  digest are hand-written and this lane consumes them as authored input. The
  lane would not notice a stale hand-computed digest — ``derive_ui`` would
  refuse typed (``classref_vendor_catalog_*``) and the arm would red, which is
  the refusal path, not a freshness check of its own.

Paths must stay symlink-free (macOS ``/tmp`` → ``/private/tmp``): the SDK's
canonical-path guard refuses a document reached through a symlink component,
and ``find_reference`` treats that refusal as "no reference matches". Pytest's
``tmp_path``/``tmp_path_factory`` roots are already canonical on every OS the
suite runs on; keep new scratch paths under them.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.classref_gate import census
from benchweave_sdk.served import active_version

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "classref"

PACKAGE = "meridian_m400_plugin"
FAMILY = "plugin-ui-class-reference"
CLASS_URN = "otdp.action.meridian_burst/1.0.0"
BURST_URN = "com.meridian.m400.burst_mode/1.0.0"
SELF_CAL_URN = "com.meridian.m400.self_cal/1.0.0"
#: The descriptor pin that carries the composed class into the derivation —
#: the one row the control arm removes.
PIN_ID = "urn:meridian:composed-burst:1.0.0"
PAGE_ID = "device-features"
COMPOSED_CONTROL = "action-burst_mode-burst_count"
CUSTOM_SECTION_TITLE = "Custom device actions"

BUILD_TIMEOUT_S = 600
CLI_TIMEOUT_S = 300
SERVE_TIMEOUT_S = 60

#: The skipped arm's reason names the remaining coverage, so a reader can tell
#: "not proven here" from "not proven at all".
SPAWN_SKIPPED_ON_WINDOWS = pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "the spawned arm stops the server with SIGINT (POSIX signal semantics); "
        "the ubuntu-only installed-wheel spawn smokes in .github/workflows/ci.yml "
        "and publish.yml are the spawned-shape coverage on Windows-hosted CI, and "
        "the non-spawn arms of this module still run there"
    ),
)


@dataclass(frozen=True)
class Installed:
    """The clean environment: a wheel of THIS tree, installed outside it."""

    root: Path
    venv: Path
    sdk: Path
    python: Path


@dataclass(frozen=True)
class LoopRun:
    """One project taken through the loop's command sequence."""

    project: Path
    package: Path
    new: subprocess.CompletedProcess[str]
    derive: subprocess.CompletedProcess[str]
    verify: subprocess.CompletedProcess[str]

    @property
    def ledger(self) -> dict[str, Any]:
        document: dict[str, Any] = json.loads(
            (self.package / "ui" / "class-reference.json").read_bytes()
        )
        return document


@dataclass(frozen=True)
class ServedPage:
    """What the spawned listener answered, and how it stopped."""

    html: str
    fragment: str
    stdout: str
    exit_code: int


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _child_env() -> dict[str, str]:
    """The child's environment with the runner's interpreter markers removed.

    The A-F3 lesson from ``tests/test_getting_started.py``: a command that
    would silently ride the runner's virtual environment must fail here
    instead. ``PYTHONNOUSERSITE`` keeps a user-site SDK copy out of the import
    path, so the console script resolves its own distribution or nothing.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP"}
    }
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _run(
    argv: list[str], *, cwd: Path, timeout: int, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
    )


def _sdk(
    installed: Installed, *arguments: str, cwd: Path
) -> subprocess.CompletedProcess[str]:
    return _run(
        [str(installed.sdk), *arguments],
        cwd=cwd,
        timeout=CLI_TIMEOUT_S,
        env=_child_env(),
    )


def _sdk_ok(
    installed: Installed, *arguments: str, cwd: Path
) -> subprocess.CompletedProcess[str]:
    completed = _sdk(installed, *arguments, cwd=cwd)
    assert completed.returncode == 0, (
        f"`benchweave-sdk {arguments[0]}` exited {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return completed


def _free_port() -> int:
    """A loopback port the OS just handed out; the bind is closed again so the
    listener can take it. The window is small and the only cost of losing it
    is a red arm, never a false green."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="session")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Installed:
    """This tree's wheel, built once and installed with both extras.

    ``[server]`` is what the preview listener needs and ``[scaffold]`` is what
    ``new`` needs; both are the real published extras, installed from the
    built wheel against the index — the same shape the CI wheel smokes use.
    """
    root = tmp_path_factory.mktemp("standalone-dev")
    dist = root / "dist"
    built = _run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=REPO,
        timeout=BUILD_TIMEOUT_S,
    )
    assert built.returncode == 0, built.stderr
    wheels = sorted(dist.glob("*.whl"))
    assert len(wheels) == 1, [path.name for path in wheels]

    venv = root / "venv"
    made = _run(["uv", "venv", str(venv)], cwd=root, timeout=BUILD_TIMEOUT_S)
    assert made.returncode == 0, made.stderr
    # The extras suffix is appended to the EXPANDED wheel path: a quoted glob
    # plus extras reaches uv as one literal and it refuses the filename (the
    # trap ci.yml's installed-wheel smoke documents).
    installed_ok = _run(
        ["uv", "pip", "install", "--python", str(venv), f"{wheels[0]}[server,scaffold]"],
        cwd=root,
        timeout=BUILD_TIMEOUT_S,
    )
    assert installed_ok.returncode == 0, installed_ok.stderr

    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    sdk = shutil.which("benchweave-sdk", path=str(bin_dir))
    python = shutil.which("python", path=str(bin_dir))
    assert sdk is not None, sorted(path.name for path in bin_dir.iterdir())
    assert python is not None, sorted(path.name for path in bin_dir.iterdir())
    return Installed(root=root, venv=venv, sdk=Path(sdk), python=Path(python))


def _scaffold(
    installed: Installed, destination: Path
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """``new --with-ui`` from the installed wheel, then the authored bytes.

    The template render comes out of the packaged copier tree (no checkout is
    reachable from the child), and the package is filled with the fixture's
    two authored documents: the descriptor and the composed declaration.
    """
    created = _sdk_ok(
        installed,
        "new",
        str(destination),
        "--package",
        PACKAGE,
        "--with-ui",
        cwd=destination.parent,
    )
    package = destination / "src" / PACKAGE
    (package / "descriptor.json").write_bytes(
        (FIXTURES / "descriptor-m400.json").read_bytes()
    )
    (package / "composed-burst.json").write_bytes(
        (FIXTURES / "composed-burst.json").read_bytes()
    )
    return destination, created


@pytest.fixture(scope="session")
def loop(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> LoopRun:
    """The developer's project, taken through the loop once for the session."""
    root = tmp_path_factory.mktemp("standalone-dev-loop")
    project, created = _scaffold(installed, root / "acme-widget")
    package = project / "src" / PACKAGE
    derive = _sdk_ok(installed, "derive-ui", str(project), cwd=root)
    verify = _sdk_ok(installed, "verify-ui", str(project), cwd=root)
    return LoopRun(
        project=project, package=package, new=created, derive=derive, verify=verify
    )


@pytest.fixture(scope="session")
def control(
    installed: Installed, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[LoopRun]:
    """The same project with ONLY the composed pin row removed.

    A ``cp`` backup holds the authored descriptor; the restore at teardown is
    asserted against the fixture bytes, so this arm cannot leave a doctored
    document behind for a later arm to consume.
    """
    root = tmp_path_factory.mktemp("standalone-dev-control")
    project, created = _scaffold(installed, root / "acme-widget")
    package = project / "src" / PACKAGE
    descriptor = package / "descriptor.json"
    backup = package / "descriptor.pin-kept.json"
    shutil.copy2(descriptor, backup)

    authored = json.loads(descriptor.read_bytes())
    stripped = {
        **authored,
        "contracts": [row for row in authored["contracts"] if row["id"] != PIN_ID],
    }
    assert len(stripped["contracts"]) == len(authored["contracts"]) - 1
    descriptor.write_bytes(_raw(stripped))

    derive = _sdk_ok(installed, "derive-ui", str(project), cwd=root)
    verify = _sdk_ok(installed, "verify-ui", str(project), cwd=root)
    try:
        yield LoopRun(
            project=project,
            package=package,
            new=created,
            derive=derive,
            verify=verify,
        )
    finally:
        shutil.copy2(backup, descriptor)
        assert descriptor.read_bytes() == (FIXTURES / "descriptor-m400.json").read_bytes()


def _fetch(
    port: int,
    path: str,
    process: subprocess.Popen[bytes],
    log: Path,
) -> str:
    """Poll one route until it answers; fail fast if the listener dies."""
    deadline = time.monotonic() + SERVE_TIMEOUT_S
    last = "no attempt"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"the preview server exited {process.returncode} before serving "
                f"{path}:\n{log.read_text(encoding='utf-8', errors='replace')}"
            )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=2
            ) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as error:
            last = str(error)
            time.sleep(0.25)
    raise AssertionError(
        f"no response from 127.0.0.1:{port}{path} within {SERVE_TIMEOUT_S}s "
        f"(last error: {last})\nlog:\n"
        f"{log.read_text(encoding='utf-8', errors='replace')}"
    )


def _serve(installed: Installed, run: LoopRun) -> ServedPage:
    """Spawn ``preview-ui``, read the page and a bare fragment, stop cleanly.

    Output goes to a file rather than a pipe: uvicorn keeps the descriptor
    open for the process's life, and a pipe nobody drains would deadlock the
    child at the buffer boundary.
    """
    port = _free_port()
    log = installed.root / f"serve-{port}.log"
    with log.open("wb") as handle:
        process = subprocess.Popen(
            [
                str(installed.sdk),
                "preview-ui",
                str(run.project),
                "--no-open",
                "--port",
                str(port),
            ],
            cwd=run.project.parent,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=_child_env(),
        )
        try:
            html = _fetch(port, f"/pages/{PAGE_ID}", process, log)
            fragment = _fetch(port, f"/pages/{PAGE_ID}/readings", process, log)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                exit_code = process.wait(timeout=SERVE_TIMEOUT_S)
            except subprocess.TimeoutExpired:  # pragma: no cover - a hung stop
                process.kill()
                exit_code = process.wait(timeout=SERVE_TIMEOUT_S)
    return ServedPage(
        html=html,
        fragment=fragment,
        stdout=log.read_text(encoding="utf-8", errors="replace"),
        exit_code=exit_code,
    )


@pytest.fixture(scope="session")
def loop_page(installed: Installed, loop: LoopRun) -> ServedPage:
    return _serve(installed, loop)


@pytest.fixture(scope="session")
def control_page(installed: Installed, control: LoopRun) -> ServedPage:
    return _serve(installed, control)


# ---------------------------------------------------------------------------
# The clean environment is the installed one.
# ---------------------------------------------------------------------------


def test_the_installed_sdk_is_the_venv_copy(installed: Installed) -> None:
    """The script under test resolves the SDK from the fresh venv, not from
    this checkout. Every other arm's value depends on this: a child that
    imported the checkout would prove the in-suite path a second time."""
    where = _run(
        [
            str(installed.python),
            "-c",
            "import benchweave_sdk, benchweave_sdk_server; "
            "print(benchweave_sdk.__file__); print(benchweave_sdk_server.__file__)",
        ],
        cwd=installed.root,
        timeout=CLI_TIMEOUT_S,
        env=_child_env(),
    )
    assert where.returncode == 0, where.stderr
    resolved = [Path(line).resolve() for line in where.stdout.split() if line.strip()]
    assert len(resolved) == 2, where.stdout
    for module_file in resolved:
        assert module_file.is_relative_to(installed.venv.resolve()), module_file
        assert not module_file.is_relative_to(REPO.resolve()), module_file


# ---------------------------------------------------------------------------
# The loop: new --with-ui → author → derive-ui → verify-ui, from the wheel.
# ---------------------------------------------------------------------------


def test_the_scaffold_renders_from_the_packaged_template(loop: LoopRun) -> None:
    """``new --with-ui`` wrote a project from the wheel's packaged copier tree
    (no checkout is reachable from the child), and the authored bytes are the
    fixture's, not something the scaffold synthesised."""
    assert "Created synthetic plugin at" in loop.new.stdout, loop.new.stdout
    assert (loop.package / "descriptor.json").read_bytes() == (
        FIXTURES / "descriptor-m400.json"
    ).read_bytes()
    assert (loop.package / "composed-burst.json").is_file()
    for member in ("adapter.py", "protocol.py", "__init__.py", "ui/manifest.json"):
        assert (loop.package / member).is_file(), member
    assert (loop.project / "pyproject.toml").is_file()


def test_derive_ui_writes_the_derived_set(loop: LoopRun) -> None:
    """``derive-ui`` exits 0 from the installed script and writes the whole
    derived set beside the package — the files the rest of the loop consumes."""
    assert "Derived the class-reference presentation set" in loop.derive.stdout
    for member in (
        "presentation.json",
        "binding-catalogue.json",
        "ui/manifest.json",
        "ui/settings/configure.schema.json",
        "ui/presets",
    ):
        assert (loop.package / member).exists(), member


def test_the_ledger_names_the_composed_mapping(loop: LoopRun) -> None:
    """The ledger's content, not a version literal: the composed action maps to
    the plugin-local class, the class row validates against whatever family
    version this SDK serves, and the residual member is inventoried custom.

    The expected family version is read from the running SDK
    (``active_version``) because a family bump lands in both halves in one arc;
    asserting a literal here would make the lane a coordination problem.
    """
    ledger = loop.ledger
    expected_version = active_version(FAMILY)
    assert {
        "action": BURST_URN,
        "resolution": "composed",
        "class": CLASS_URN,
    } in ledger["composed_actions"]
    assert any(
        row.get("class") == CLASS_URN and row.get("validated_against") == expected_version
        for row in ledger["composed_classes"]
    ), (ledger["composed_classes"], expected_version)
    assert any(
        row.get("action") == SELF_CAL_URN and row.get("resolution") == "custom"
        for row in ledger["custom_actions"]
    ), ledger["custom_actions"]
    assert not any(
        row.get("action") == BURST_URN for row in ledger["custom_actions"]
    ), ledger["custom_actions"]


def test_verify_ui_gates_clean_and_reports_the_residual_member(loop: LoopRun) -> None:
    """``verify-ui`` exits 0 with the rendered gate clean and the residual
    member disclosed on the REPORTED channel; the disclosure is a report, not
    a finding, so its presence must not turn the gate red."""
    assert "Rendered gate clean" in loop.verify.stdout, loop.verify.stdout
    assert f"reported deviation: custom: {SELF_CAL_URN}" in loop.verify.stdout, (
        loop.verify.stdout
    )


# ---------------------------------------------------------------------------
# The spawned listener — the composed surface over HTTP.
# ---------------------------------------------------------------------------


@SPAWN_SKIPPED_ON_WINDOWS
def test_the_served_page_carries_the_composed_control(loop_page: ServedPage) -> None:
    """The composed action's control and button are on the served page.

    ``action-burst_mode-burst_count`` cannot come from the descriptor: the
    fixture's ``burst_mode`` action declares ``input_constraints: {}``, so the
    field set is the composed class's ``input_schema`` or nothing.
    """
    seen = census(loop_page.html)
    assert COMPOSED_CONTROL in seen["staged_control_ids"], seen["staged_control_ids"]
    assert "burst_mode" in seen["buttons"], seen["buttons"]
    assert CUSTOM_SECTION_TITLE in loop_page.html


@SPAWN_SKIPPED_ON_WINDOWS
def test_the_served_page_carries_every_mode_banner(loop_page: ServedPage) -> None:
    """Every banner entry the host's own rule yields for the mock transport is
    on the served page, import-compared against ``mode_banner_entries`` — the
    denominator is the mechanism, not a hand-listed set.

    The bare fragment from the same listener carries none of them, which is
    the discriminator: the check measures the shell's banner, so a page that
    stopped rendering its shell could not pass it by coincidence.
    """
    from benchweave_sdk_server.presentation import mode_banner_entries

    entries = mode_banner_entries(simulated=True).modes
    assert entries, "the mock transport yields at least one banner entry"
    for entry in entries:
        assert entry.wording in loop_page.html, (entry.key, entry.wording)
        assert entry.wording not in loop_page.fragment, (entry.key, entry.wording)


@SPAWN_SKIPPED_ON_WINDOWS
def test_the_console_script_announces_the_listener_and_stops_cleanly(
    loop_page: ServedPage,
) -> None:
    """The console script's own banner names the package and the URL, the
    bearer line is printed (the mock has no mutations to gate, but the token
    line is part of the banner contract), and SIGINT exits 0 — the stop a
    developer actually performs."""
    assert f"Serving {PACKAGE} on http://127.0.0.1:" in loop_page.stdout, loop_page.stdout
    assert "Bearer token (REST mutations and MCP over HTTP): " in loop_page.stdout, (
        loop_page.stdout
    )
    assert loop_page.exit_code == 0, loop_page.stdout


# ---------------------------------------------------------------------------
# The control arm — the discriminator the composed assertions must flip on.
# ---------------------------------------------------------------------------


@SPAWN_SKIPPED_ON_WINDOWS
def test_the_composed_surface_disappears_without_the_pin(
    control: LoopRun, control_page: ServedPage, loop_page: ServedPage
) -> None:
    """Remove ONLY the composed pin row and the composed surface is gone.

    Both commands still exit 0 (the residual path is a disclosure, not a
    refusal), the ledger loses the composed mapping and inventories the action
    as custom, ``verify-ui`` names it ``custom, renders nothing`` — and the
    served page loses the control and the button while keeping the residual
    member's own control and section. The authored documents are identical
    apart from that one row (asserted from the fixture bytes below), so the
    only cause of the disappearance is the pin.
    """
    authored = json.loads((FIXTURES / "descriptor-m400.json").read_bytes())
    stripped = json.loads((control.package / "descriptor.json").read_bytes())
    expected = {
        **authored,
        "contracts": [row for row in authored["contracts"] if row["id"] != PIN_ID],
    }
    assert stripped == expected, "the control descriptor differs by more than the pin row"

    assert not control.ledger["composed_actions"], control.ledger["composed_actions"]
    assert any(
        row.get("action") == BURST_URN for row in control.ledger["custom_actions"]
    ), control.ledger["custom_actions"]
    assert "Rendered gate clean" in control.verify.stdout, control.verify.stdout
    assert (
        f"reported deviation: custom, renders nothing: {BURST_URN}"
        in control.verify.stdout
    ), control.verify.stdout

    seen = census(control_page.html)
    assert COMPOSED_CONTROL not in seen["staged_control_ids"], seen["staged_control_ids"]
    assert "burst_mode" not in seen["buttons"], seen["buttons"]
    # The residual member and the composed control's sibling surfaces stay:
    # the arm removes the pin, not the derivation.
    assert "action-self_cal-channel" in seen["staged_control_ids"]
    assert CUSTOM_SECTION_TITLE in control_page.html
    # The paired positive half, measured the same way on the OTHER listener:
    # two spawned servers, one census function, and the pin row as the only
    # difference between their projects.
    assert COMPOSED_CONTROL in census(loop_page.html)["staged_control_ids"]
