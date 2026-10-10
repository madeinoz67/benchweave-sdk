"""Issue #422 increment 3 — the SDK lifecycle twins (S1/S2/S3).

The design authority is the gateway's supervision record §5 + §7 (one
standard, per-surface application): S1 start/stop/status happy path
(pidfile verifies, the token delivery file written 0600 and NEVER leaked
into the log, exit 0); S2 the wedge ladder (SIGTERM ignored → bounded
wait → one audited SIGKILL row); S3 ``--protective`` is ABSENT from the
CLI surface (help enumeration — the recorded divergence is pinned, not
assumed).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from click.testing import CliRunner

from benchweave_sdk_server import lifecycle
from benchweave_sdk_server.cli import cli

REPO = Path(__file__).resolve().parents[2]
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="signal-path arm: POSIX only"
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return cast(int, sock.getsockname()[1])


@pytest.fixture()
def bindings_file(tmp_path: Path) -> Path:
    """The supervision family's anchor: a bindings document path in a
    scratch root (the family derives beside it; the file itself need not
    exist for the resolution — an explicit path is taken as named)."""
    return tmp_path / "device-bindings.json"


def _run(*args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "benchweave_sdk_server.cli", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@POSIX_ONLY
def test_s1_start_stop_status_happy_path(
    starter_project: Path, bindings_file: Path
) -> None:
    """S1: start → the pidfile verifies, the tokens file is written 0600
    with the per-launch bearer, the log file exists and does NOT contain
    the token; the host serves; stop → exit 0, process gone, pidfile
    removed, journal rows `stop_requested` + `stopped`; status → the
    absent verdict."""
    port = _free_port()
    started = _run(
        "start", str(starter_project),
        "--bindings", str(bindings_file),
        "--host", "127.0.0.1", "--port", str(port),
    )
    assert started.returncode == 0, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    pid = int(payload["pid"])
    record = lifecycle.read_pidfile(bindings_file)
    assert record is not None and int(record["pid"]) == pid
    assert record["server"] == "benchweave-sdk-server"
    assert record["log_destination"] == str(lifecycle.log_path(bindings_file))

    tokens_file = lifecycle.tokens_path(bindings_file)
    assert tokens_file.exists(), "started mode delivers the tokens file"
    assert tokens_file.stat().st_mode & 0o777 == 0o600
    tokens = json.loads(tokens_file.read_text())
    bearer = str(tokens["bearer_token"])
    assert bearer, "the per-launch bearer rides the file (F5 fold)"

    log_file = lifecycle.log_path(bindings_file)
    deadline = time.monotonic() + 10.0
    while not log_file.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert log_file.exists(), "stderr went to <bindings>.log"
    # F5 fold: the credential NEVER reaches the log bytes.
    assert bearer not in log_file.read_text(errors="replace")

    # The host serves with the delivered bearer.
    with httpx.Client(
        base_url=f"http://127.0.0.1:{port}", timeout=5.0,
        headers={"Authorization": f"Bearer {bearer}"},
    ) as client:
        deadline = time.monotonic() + 30.0
        while True:
            try:
                response = client.get("/")
                if response.status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline, "started host never served"

    stopped = _run("stop", "--bindings", str(bindings_file))
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    # The doorbell's machine-check: the daemon's OWN poll consumed the
    # request and rewrote it into the accepted verdict (the signal path
    # alone — uvicorn's graceful handler — would stop the host without
    # the file ever being read; this assert is what gives the poll mount
    # teeth, per the record's RED control (a)).
    assert json.loads(stopped.stdout).get("verdict") == "accepted", (
        stopped.stdout + stopped.stderr
    )
    consumed = lifecycle.read_stop_file(bindings_file)
    assert consumed is not None and consumed.get("status") == "accepted"
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.2)
        except OSError:
            break
    else:
        raise AssertionError("the stopped host is still alive")
    assert lifecycle.read_pidfile(bindings_file) is None
    rows = [
        json.loads(line)
        for line in lifecycle.journal_path(bindings_file).read_text().splitlines()
    ]
    events = [row["event"] for row in rows]
    assert "stop_requested" in events
    assert events[-1] == "stopped"

    status = _run("status", "--bindings", str(bindings_file))
    assert status.returncode == 0, status.stdout + status.stderr
    assert json.loads(status.stdout)["pid"]["verdict"] == "absent"


@POSIX_ONLY
def test_s2_wedge_ladder_bounded_wait_then_one_sigkill(
    bindings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2: a host that ignores SIGTERM (the wedge) → the bounded wait
    expires → ONE audited SIGKILL (`sigkill_sent`, reason
    `wedge_wait_exceeded`), the CLI exits non-zero disclosing the kill.
    The wedge is a real subprocess with SIG_IGN on SIGTERM; the bounded
    wait is tightened via the module constant the CLI reads at call time
    (a service parameter, not a bench envelope — no commissioned window
    exists on this surface)."""
    monkeypatch.setattr(lifecycle, "WEDGE_WAIT_S", 2.0)
    wedge = subprocess.Popen(
        [
            sys.executable, "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);"
            " print('ready', flush=True); time.sleep(120)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert wedge.stdout is not None
        assert wedge.stdout.readline().strip() == "ready"
        # The pidfile is staged by hand (the L6-style fixture shape): the
        # wedge's REAL pid + REAL start time, so the identity verdict is
        # OURS and the ladder is what the arm exercises.
        lifecycle.pid_path(bindings_file).write_text(
            json.dumps(
                {
                    "pid": wedge.pid,
                    "server": "benchweave-sdk-server",
                    "bindings": str(bindings_file),
                    "started_wall": "2026-10-08T00:00:00Z",
                    "started_ticks": lifecycle.process_start_ticks(wedge.pid),
                    "log_destination": "stderr",
                    "schema": 1,
                }
            ),
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            cli, ["stop", "--bindings", str(bindings_file)]
        )
        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "supervision_sigkill" in combined
        assert "wedge_wait_exceeded" in combined
        assert "STILL ALIVE" not in combined, "one SIGKILL must land"
        rows = [
            json.loads(line)
            for line in lifecycle.journal_path(bindings_file)
            .read_text()
            .splitlines()
        ]
        kills = [row for row in rows if row["event"] == "sigkill_sent"]
        assert len(kills) == 1, rows
        assert kills[0]["reason"] == "wedge_wait_exceeded"
        assert kills[0]["target_pid"] == wedge.pid
    finally:
        if wedge.poll() is None:
            wedge.kill()
            wedge.wait(timeout=10)


def test_s3_no_protective_flag_anywhere_on_the_cli_surface() -> None:
    """S3: ``--protective`` does not exist on this CLI — the recorded
    divergence (no procedures, no store, no commissioned safe transition)
    pinned by enumerating EVERY command's --help, not by assuming."""
    top = CliRunner().invoke(cli, ["--help"])
    assert top.exit_code == 0
    commands = [
        word for word in top.output.split()
        if word.isalpha() and word not in {"Standalone", "BenchWeave", "host:"}
    ]
    assert {"serve", "stop", "start", "status", "restart"} <= set(commands), (
        f"the lifecycle verbs must be on the surface: {sorted(commands)}"
    )
    seen: list[str] = [top.output]
    for name in sorted(set(commands)):
        result = CliRunner().invoke(cli, [name, "--help"])
        if result.exit_code == 0:
            seen.append(result.output)
    everything = "\n".join(seen)
    assert "--protective" not in everything, (
        "the SDK surface records its divergence from the one standard by "
        "REFUSING the flag's existence, not by ignoring it"
    )


def test_service_install_refused_with_the_recorded_reason() -> None:
    """The §5 table's REFUSED row, verbatim reason on stderr, exit 2 (the
    shim pattern's refusal class)."""
    result = CliRunner().invoke(cli, ["service", "install"])
    assert result.exit_code == 2
    combined = result.output + (result.stderr or "")
    assert "benchweave_sdk_service_refused" in combined
    assert "not a boot daemon" in combined


# --- the inc3 refute fold arms (2026-10-08): S1-S7 -------------------------------


def _started(
    starter_project: Path, bindings_file: Path, port: int
) -> dict[str, object]:
    """`start` the host and return its JSON payload (the S1 arm's shape)."""
    started = _run(
        "start", str(starter_project),
        "--bindings", str(bindings_file),
        "--host", "127.0.0.1", "--port", str(port),
    )
    assert started.returncode == 0, started.stdout + started.stderr
    return dict(json.loads(started.stdout))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _await_listening(
    port: int, host: str = "127.0.0.1", timeout: float = 30.0
) -> None:
    """Bridge the pidfile→listen gap before a client connects (#427 fold
    row 1). The supervised child's readiness handle is its PIDFILE — S7
    delivers it before ``_run_supervised`` reaches uvicorn's bind — so
    ``start`` returns while the socket may not accept yet. A client that
    fires its connect on pidfile-readiness alone races the listener: under
    ``-n auto`` load the gap stretches past the connect and the arm dies
    ``Connection refused`` (2 of 10 full xdist runs in the #427 battery).
    Retry the TCP connect until the port accepts — the listener is the
    seam this waits for, not an HTTP response (that stronger wait is the
    S1 arm's own loop)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def _journal_rows(bindings_file: Path) -> list[dict[str, object]]:
    path = lifecycle.journal_path(bindings_file)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
    ]


@POSIX_ONLY
def test_s1_stale_stop_request_is_not_the_new_daemons_to_consume(
    starter_project: Path, bindings_file: Path
) -> None:
    """S1: a hand-written unconsumed request bound to a DEAD launch is
    not the new host's to consume — era-bound requests only. RED against
    the inc3 build: the host consumes it within one poll cadence and
    stops itself (the stale-request suicide). The stale request lands
    AFTER the boot (start's own clear would remove a pre-boot one — the
    start leg has its own arm below); this arm pins the RUNNING host's
    doorbell refusal."""
    payload = _started(starter_project, bindings_file, _free_port())
    pid = int(payload["pid"])  # type: ignore[arg-type]
    try:
        lifecycle.stop_path(bindings_file).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "mode": "plain",
                    "requested_wall": "2026-10-08T00:00:00Z",
                    "actor_pid": os.getpid(),
                    "target_pid": 999999,  # a launch that no longer exists
                }
            ),
            encoding="utf-8",
        )
        # ≥ 3 doorbell cadences past the write: a consuming host is gone
        # within one.
        time.sleep(3.0)
        assert _alive(pid), (
            "the host consumed a request bound to a dead launch and "
            "stopped itself (the stale-request suicide, S1)"
        )
        leftover = lifecycle.read_stop_file(bindings_file)
        assert leftover is not None and "status" not in leftover, (
            "a request not bound to this launch is never consumed"
        )
    finally:
        subprocess.run(
            [sys.executable, "-m", "benchweave_sdk_server.cli", "stop",
             "--bindings", str(bindings_file)],
            cwd=str(REPO), capture_output=True, text=True, timeout=60,
        )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="the windows start path never reaches readiness with an empty "
    "daemon log (three rollups, two fix waves) — tracked in issue #432; "
    "the stale-request CLEAR logic itself stays unit-pinned "
    "cross-platform below",
)
def test_s1_start_clears_unconsumed_stale_requests(
    starter_project: Path, bindings_file: Path
) -> None:
    """S1, the start leg: `start` clears unconsumed stale requests before
    spawning (typed journal note) so the launch boots clean."""
    lifecycle.stop_path(bindings_file).write_text(
        json.dumps(
            {
                "schema": 1,
                "mode": "plain",
                "requested_wall": "2026-10-08T00:00:00Z",
                "actor_pid": os.getpid(),
                "target_pid": 999999,
            }
        ),
        encoding="utf-8",
    )
    _started(starter_project, bindings_file, _free_port())
    try:
        cleared = [
            row
            for row in _journal_rows(bindings_file)
            if row.get("event") == "stale_stop_request_cleared"
        ]
        assert cleared, (
            "start journals the typed stale-request clear (S1): "
            f"{_journal_rows(bindings_file)}"
        )
        assert not lifecycle.stop_path(bindings_file).exists(), (
            "the stale request is gone before the child boots"
        )
    finally:
        subprocess.run(
            [sys.executable, "-m", "benchweave_sdk_server.cli", "stop",
             "--bindings", str(bindings_file)],
            cwd=str(REPO), capture_output=True, text=True, timeout=60,
        )


@POSIX_ONLY
def test_s2_open_events_stream_does_not_wedge_the_stop(
    starter_project: Path, bindings_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S2 (the gateway's F2 fix, twin): one open /events tab must not
    route every stop to the kill rung — the stop decision closes live
    SSE streams and the serve config carries an explicit
    ``timeout_graceful_shutdown``. RED against the inc3 build: the open
    stream hangs the drain past the wedge wait → the SIGKILL rung → a
    non-zero exit over a HEALTHY host."""
    import httpx

    monkeypatch.setattr(lifecycle, "WEDGE_WAIT_S", 3.0)
    payload = _started(starter_project, bindings_file, _free_port())
    pid = int(payload["pid"])  # type: ignore[arg-type]
    port = int(payload["port"])  # type: ignore[arg-type]
    tokens = json.loads(
        lifecycle.tokens_path(bindings_file).read_text()
    )
    bearer = str(tokens["bearer_token"])
    # The pidfile says the child LIVES; only the listener says it serves.
    # Wait for the bind before the stream connect (#427 fold row 1: the
    # naive connect raced the listener 2 of 10 full xdist runs).
    _await_listening(port)
    try:
        with (
            httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=5.0,
                headers={"Authorization": f"Bearer {bearer}"},
            ) as client,
            client.stream("GET", "/events") as stream,
        ):
            assert stream.status_code == 200
            result = CliRunner().invoke(
                cli, ["stop", "--bindings", str(bindings_file)]
            )
            assert result.exit_code == 0, (
                "the stop over one open /events tab must drain and "
                f"exit 0, not escalate:{result.output}"
                f"{(result.stderr or '')}"
            )
        kills = [
            row for row in _journal_rows(bindings_file)
            if row.get("event") == "sigkill_sent"
        ]
        assert not kills, (
            "a healthy host with one open events tab was SIGKILLed — "
            "the wedge the SSE close exists to prevent (S2)"
        )
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_await_listening_bridges_the_refused_window() -> None:
    """The S2 flake's window, made deterministic (#427 fold row 1): a
    listener that delays its bind by one second reproduces with certainty
    what load stretches past the connect under ``-n auto`` — the naive
    single connect is REFUSED inside the window (the 2-of-10 xdist
    ``Connection refused`` shape), and ``_await_listening`` returns only
    once the port accepts. The window is the pidfile→bind gap: the
    supervised child's readiness handle precedes uvicorn's listen, so any
    client firing on pidfile-readiness alone needs this bridge."""
    import threading

    port = _free_port()

    def delayed_listener() -> None:
        time.sleep(1.0)  # the pidfile→bind gap, made deterministic
        with socket.socket() as server:
            server.bind(("127.0.0.1", port))
            server.listen(8)
            server.settimeout(0.5)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                conn.close()

    threading.Thread(target=delayed_listener, daemon=True).start()
    # Inside the window the naive connect is refused — the deterministic
    # shape of the xdist flake this arm pins.
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1.0).close()
    # The bridge crosses exactly this window.
    _await_listening(port, timeout=10.0)


def test_s3_ticks_null_identity_is_pid_unknown_not_stale(
    bindings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3: a pid whose start time cannot be read — on EITHER side of the
    comparison — is an UNKNOWN identity, never a stale one: `stop`
    answers `supervision_pid_unknown:` (the conservative direction;
    there is no hold to vouch). The recorded-null shape is the defect
    the fold fixes: a pidfile written where ticks were unreadable is
    not evidence of a recycled pid."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    def _stage_pidfile(ticks: object) -> None:
        lifecycle.pid_path(bindings_file).write_text(
            json.dumps(
                {
                    "pid": child.pid,
                    "server": "benchweave-sdk-server",
                    "bindings": str(bindings_file),
                    "started_wall": "2026-10-08T00:00:00Z",
                    "started_ticks": ticks,
                    "log_destination": "stderr",
                    "schema": 1,
                }
            ),
            encoding="utf-8",
        )

    try:
        # Shape 1: the LIVE read is unobtainable.
        _stage_pidfile(12345)
        monkeypatch.setattr(lifecycle, "process_start_ticks", lambda pid: None)
        result = CliRunner().invoke(
            cli, ["stop", "--bindings", str(bindings_file)]
        )
        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "supervision_pid_unknown:" in combined, combined
        assert "supervision_stale_pid:" not in combined, combined
        # Shape 2: the RECORDED value is null, the live read obtainable —
        # the comparison cannot be made either way.
        _stage_pidfile(None)
        monkeypatch.setattr(lifecycle, "process_start_ticks", lambda pid: 54321)
        result = CliRunner().invoke(
            cli, ["stop", "--bindings", str(bindings_file)]
        )
        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "supervision_pid_unknown:" in combined, combined
        assert "supervision_stale_pid:" not in combined, combined
        assert _alive(child.pid), "an unknown identity signals NOTHING"
    finally:
        child.terminate()
        child.wait(timeout=10)


@POSIX_ONLY
def test_s4_mode_literal_and_the_cli_journals_the_consumption(
    starter_project: Path, bindings_file: Path
) -> None:
    """S4: the request/verdict mode literal is `plain` (the one standard
    the gateway vocabulary carries — `stop` names the VERB, never the
    mode), and the DAEMON no longer writes the stop_consumed journal row
    — the verdict file carries the fields and the CLI (the journal's one
    writer) journals them on observation."""
    payload = _started(starter_project, bindings_file, _free_port())
    try:
        stopped = _run("stop", "--bindings", str(bindings_file))
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        consumed = lifecycle.read_stop_file(bindings_file) or {}
        assert consumed.get("mode") == "plain", consumed
        rows = _journal_rows(bindings_file)
        consumed_rows = [
            row for row in rows if row.get("event") == "stop_consumed"
        ]
        assert len(consumed_rows) == 1, rows
        # The CLI-side observation carries the VERDICT's fields — the
        # daemon-side row (pre-fold) carried only its own pid.
        assert consumed_rows[0].get("server_pid") == payload["pid"], rows
        assert consumed_rows[0].get("decided_wall"), rows
        stopped_rows = [row for row in rows if row.get("event") == "stopped"]
        assert stopped_rows and stopped_rows[-1].get("mode") == "plain", rows
    finally:
        subprocess.run(
            [sys.executable, "-m", "benchweave_sdk_server.cli", "stop",
             "--bindings", str(bindings_file)],
            cwd=str(REPO), capture_output=True, text=True, timeout=60,
        )


requires_posix_mode_bits = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Path.chmod(0o500) cannot make a directory unwritable on Windows "
        "(the read-only attribute applies to files, not directories), so "
        "the E2E provocation is POSIX-only; the refusal path itself is "
        "pinned cross-platform by test_s5_typed_refusal_is_cross_platform"
    ),
)

#: The file-chmod arms' own gate (W8: S6's skip reason names the
#: FILE-chmod/ACL story, not the directory-chmod one above). The tokens
#: file is a FILE: mode bits do reach it on POSIX; on Windows mode bits
#: do not reach the ACL, so the group-readable provocation cannot be
#: staged there — ``deliver_tokens`` restricts the ACL at write time
#: instead (the atrest #137 posture), and the doctor row carries the
#: Windows disclosure.
requires_posix_file_perms = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Path.chmod(0o644) on the tokens FILE cannot widen the Windows "
        "ACL (mode bits do not reach it), so the group-readable "
        "provocation is POSIX-only; on Windows deliver_tokens restricts "
        "the ACL at write time and the doctor row carries the disclosure"
    ),
)


@requires_posix_mode_bits
def test_s5_read_only_parent_is_a_typed_refusal(
    starter_project: Path, bindings_file: Path
) -> None:
    """S5: a supervision family whose parent directory is read-only is a
    TYPED refusal — never a raw PermissionError traceback."""
    parent = bindings_file.parent
    parent.chmod(0o500)
    try:
        result = CliRunner().invoke(
            cli, ["stop", "--bindings", str(bindings_file)]
        )
        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "supervision_refused_unwritable:" in combined, (
            f"the read-only parent must refuse typed: {combined}"
        )
        assert "PermissionError" not in combined, (
            "no raw traceback reaches the operator (S5)"
        )
    finally:
        parent.chmod(0o700)


def test_s6_probe_windows_reads_the_real_last_error() -> None:
    """S6: the Windows probe's error classification only works through a
    WinDLL created with ``use_last_error=True`` — ``ctypes.get_last_error``
    reads the swap slot that flag maintains; the cached ``windll``
    instance leaves it at 0 and every OpenProcess failure misreads
    `unknown` (dead(87)/running(5) never fire). Pinned at source level:
    the behavior arm rides the Windows CI leg (the W1 posture)."""
    import inspect

    source = inspect.getsource(lifecycle._probe_windows)
    assert "use_last_error=True" in source, (
        "the probe must create its WinDLL with use_last_error=True (S6)"
    )


@POSIX_ONLY
def test_s7_tokens_file_lands_before_the_pidfile(
    starter_project: Path, bindings_file: Path
) -> None:
    """S7: under `start`, the tokens file is written BEFORE the pidfile —
    readiness (the pidfile naming the child) then implies the tokens were
    deliverable. The observable: a boot that cannot protect the tokens
    (a read-only parent) fails BEFORE any pidfile exists — no stale
    handle is left over a boot that never became ready."""
    parent = bindings_file.parent
    parent.mkdir(parents=True, exist_ok=True)
    parent.chmod(0o500)
    try:
        started = _run(
            "start", str(starter_project),
            "--bindings", str(bindings_file),
            "--host", "127.0.0.1", "--port", str(_free_port()),
            timeout=90,
        )
        assert started.returncode != 0, (
            "a boot that cannot write the family must fail, not hang"
        )
        assert not lifecycle.pid_path(bindings_file).exists(), (
            "the tokens write precedes the pidfile: a failed delivery "
            "leaves NO readiness handle behind (S7)"
        )
    finally:
        parent.chmod(0o700)


def test_s7_source_order_tokens_before_pidfile() -> None:
    """S7's ordering half, pinned at source level (the behavioral
    observable — a failed tokens delivery leaving no pidfile — cannot
    discriminate order on POSIX, where one read-only parent blocks both
    writes equally): the supervised boot delivers the tokens BEFORE it
    writes the readiness handle."""
    import inspect

    from benchweave_sdk_server import cli as cli_module

    source = inspect.getsource(cli_module)
    supervised_block = source[source.index("if supervised:"):]
    tokens_at = supervised_block.index("deliver_tokens(")
    pidfile_at = supervised_block.index("write_pidfile(")
    assert tokens_at < pidfile_at, (
        "the tokens file must land before the pidfile — readiness then "
        "implies the tokens were deliverable (S7)"
    )


# --- the windows-fix wave arms (2026-10-08, fix wave 2) ----------------------------


def test_s5_typed_refusal_is_cross_platform(
    bindings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5's refusal PATH with no mode bits (the E2E provocation above is
    POSIX-only): an unwritable family surfaces as the TYPED refusal on
    every platform — the refusal machinery (stop's `_unwritable` wrapper
    + the CLI's LifecycleError catch), not chmod semantics, is what S5
    pins. Windows CI evidence: the chmod arm read `assert 0 != 0` there
    because 0o500 leaves a directory writable on win32."""
    from benchweave_sdk_server import lifecycle as lifecycle_module

    def _denied(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(lifecycle_module, "journal_append", _denied)
    result = CliRunner().invoke(cli, ["stop", "--bindings", str(bindings_file)])
    assert result.exit_code != 0, result.output + (result.stderr or "")
    combined = result.output + (result.stderr or "")
    assert "supervision_refused_unwritable:" in combined, combined
    assert "PermissionError" not in combined, "no raw traceback (S5)"


def test_w3_acl_consult_budget_fits_the_readiness_window() -> None:
    """The Windows tokens-protection consults (whoami + icacls) are BOUNDED
    subprocess calls in the child's PRE-readiness path. Their combined
    budget must fit inside start's readiness window, or a stuck consult is
    structurally unwitnessable: the parent times out at 30s with an empty
    log tail while the child sits silently inside its own 30s timeout —
    exactly the windows CI failure shape (`start_failed: no readiness
    within 30s; log tail: (empty)`). 2 x 30 > 30 was that defect."""
    budget = getattr(lifecycle, "_ACL_CONSULT_TIMEOUT_S", None)
    assert budget is not None, "the consults carry a named budget constant"
    assert 2 * budget < lifecycle.START_READINESS_S, (
        f"2 x {budget}s of bounded consults must fit inside the "
        f"{lifecycle.START_READINESS_S:.0f}s readiness window, or a stuck "
        "consult can only surface as the parent's silent timeout"
    )


def test_w3_windows_refused_tokens_delivery_is_typed_not_raw(
    starter_project: Path, bindings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The supervised boot's refusal catch covers the WINDOWS token path:
    `_restrict_windows` refuses with LifecycleError (unreadable SID,
    failed ACL restriction, stuck consult) — NOT OSError — and that must
    surface as the typed `supervision_refused_unwritable` refusal, never
    a raw LifecycleError traceback. Windows CI evidence: the failing boot
    died silent, so this path had no cross-platform pin at all."""
    monkeypatch.setenv(
        "BENCHWEAVE_STANDALONE_BINDINGS", str(bindings_file.resolve())
    )

    def _refuse(*args: object, **kwargs: object) -> None:
        raise lifecycle.LifecycleError(
            "cannot protect the tokens file: the current user's SID was "
            "unreadable — no token file was written"
        )

    monkeypatch.setattr(lifecycle, "deliver_tokens", _refuse)
    result = CliRunner().invoke(
        cli,
        ["serve", str(starter_project), "--no-open", "--supervised"],
    )
    assert result.exit_code != 0, result.output + (result.stderr or "")
    combined = result.output + (result.stderr or "")
    assert "supervision_refused_unwritable" in combined, (
        "the windows refusal path must carry the typed prefix, not a raw "
        f"traceback: {combined}"
    )
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"must be a handled refusal, not a raw exception: "
        f"{result.exception!r}"
    )


def test_w3_spawn_kwargs_are_platform_honest(
    starter_project: Path, bindings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`start`'s detachment is platform-split: POSIX keeps
    start_new_session (setsid); win32 passes the DETACHED_PROCESS |
    CREATE_NEW_PROCESS_GROUP creationflags instead — CPython SILENTLY
    IGNORES start_new_session on win32 (its Windows _execute_child takes
    it as `unused_start_new_session`), so the unconditional kwarg claimed
    a detachment that did not exist there."""
    captured: dict[str, object] = {}

    class _FakeProc:
        pid = 4242
        returncode = 1

        def poll(self) -> int:
            return 1  # exit the readiness loop on the first check

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 1

    def _capture(argv: list[str], **kwargs: object) -> object:
        captured.clear()
        captured.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(
        lifecycle.subprocess, "Popen", _capture
    )
    # POSIX branch: setsid detachment, no creationflags.
    monkeypatch.setattr(lifecycle, "_POSIX", True)
    with pytest.raises(lifecycle.LifecycleError, match="start_failed"):
        lifecycle.start(
            starter_project, bindings=bindings_file, host="127.0.0.1",
            port=8477, transport="mock", device=None, scenario=None,
        )
    assert captured.get("start_new_session") is True, captured
    assert "creationflags" not in captured, captured
    # Windows branch: the ignored kwarg is GONE, the creationflags twin
    # carries the detachment instead.
    monkeypatch.setattr(lifecycle, "_POSIX", False)
    with pytest.raises(lifecycle.LifecycleError, match="start_failed"):
        lifecycle.start(
            starter_project, bindings=bindings_file, host="127.0.0.1",
            port=8477, transport="mock", device=None, scenario=None,
        )
    assert "start_new_session" not in captured, (
        "CPython silently ignores start_new_session on win32 — passing "
        f"it claims a detachment that does not exist: {captured}"
    )
    # The frozen Win32 API constants (a POSIX subprocess module does not
    # carry them, so the literal is the honest cross-host spelling):
    # DETACHED_PROCESS 0x8 | CREATE_NEW_PROCESS_GROUP 0x200.
    assert captured.get("creationflags") == 0x00000208, captured


# --- the doctor + logs twins (issue #422 increment 4 — one standard,
# --- per-surface application; the gateway record's §3 as folded) -------------------


def _stage_twin_pidfile(bindings_file: Path, log_destination: str) -> None:
    lifecycle.pid_path(bindings_file).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "server": "benchweave-sdk-server",
                "bindings": str(bindings_file),
                "started_wall": "2026-10-09T00:00:00Z",
                "started_ticks": lifecycle.process_start_ticks(os.getpid()),
                "log_destination": log_destination,
                "schema": 1,
            }
        ),
        encoding="utf-8",
    )


def _stage_tokens(bindings_file: Path, bearer: str = "sdk-tok-9d2f") -> str:
    lifecycle.tokens_path(bindings_file).write_text(
        json.dumps({"bearer_token": bearer, "url": "http://127.0.0.1:8477"}),
        encoding="utf-8",
    )
    lifecycle.tokens_path(bindings_file).chmod(0o600)
    return bearer


def _twins_combined(result: object) -> str:
    output = getattr(result, "output", "")
    try:
        err = getattr(result, "stderr", "") or ""
    except ValueError:
        err = ""
    return output + err


def _twin_rows(result: object) -> list[dict[str, object]]:
    parsed = json.loads(cast(str, getattr(result, "output", "")))
    return list(cast(dict[str, object], parsed).get("checks", []))


def _twin_row(result: object, check: str) -> dict[str, object]:
    rows = [row for row in _twin_rows(result) if row.get("check") == check]
    assert len(rows) == 1, f"expected one {check!r} row: {rows}"
    return rows[0]


def test_s5_doctor_happy_path(bindings_file: Path) -> None:
    """S5: a staged pidfile naming this process (ours), a staged log with
    the path destination, a 0600 tokens file — every row passes, exit 0;
    the bearer VALUE never reaches output."""
    log = lifecycle.log_path(bindings_file)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("serve line\n", encoding="utf-8")
    _stage_twin_pidfile(bindings_file, str(log))
    bearer = _stage_tokens(bindings_file)
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert result.exit_code == 0, _twins_combined(result)
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert len(payload["checks"]) == 5, payload["checks"]
    for row in payload["checks"]:
        assert row["verdict"] == "pass", row
    assert bearer not in _twins_combined(result)
    assert _twin_row(result, "pid")["verdict"] == "pass"
    assert _twin_row(result, "log_destination")["verdict"] == "pass"
    assert _twin_row(result, "tokens")["verdict"] == "pass"


@requires_posix_file_perms
def test_s6_group_readable_tokens_fails_without_leaking_the_bearer(
    bindings_file: Path,
) -> None:
    """S6: tokens chmod 0644 — the tokens row fails (the perms check is
    the whole reason this check exists SDK-side) and the bearer VALUE is
    absent from output. POSIX-only provocation (mode bits; on Windows the
    check is skip-with-disclosure and deliver_tokens restricts the ACL at
    write time)."""
    _stage_twin_pidfile(bindings_file, "stderr")
    bearer = _stage_tokens(bindings_file)
    lifecycle.tokens_path(bindings_file).chmod(0o644)
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert result.exit_code == 1, _twins_combined(result)
    row = _twin_row(result, "tokens")
    assert row["verdict"] == "fail"
    assert bearer not in _twins_combined(result)


def test_s7_logs_tails_the_staged_log(
    starter_project: Path, bindings_file: Path
) -> None:
    """S7: logs tails a staged <bindings>.log through the pidfile's path
    destination; the payload names the destination and carries the
    lines."""
    log = lifecycle.log_path(bindings_file)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "\n".join(f"twin-line-{index:03d}" for index in range(10)) + "\n",
        encoding="utf-8",
    )
    _stage_twin_pidfile(bindings_file, str(log))
    result = CliRunner().invoke(
        cli,
        ["logs", str(starter_project), "--bindings", str(bindings_file),
         "--lines", "4"],
    )
    assert result.exit_code == 0, _twins_combined(result)
    payload = json.loads(result.output)
    assert payload["destination"] == str(log)
    assert payload["lines"] == [
        "twin-line-006", "twin-line-007", "twin-line-008", "twin-line-009",
    ]
    # The domain refusal is typed on this surface too (the R8 fold).
    bad = CliRunner().invoke(
        cli,
        ["logs", str(starter_project), "--bindings", str(bindings_file),
         "--lines", "0"],
    )
    assert bad.exit_code == 1, _twins_combined(bad)
    assert "logs_lines_domain:" in _twins_combined(bad)


def test_s8_tokens_file_is_never_a_destination(
    starter_project: Path, bindings_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S8: (rung 1) a pidfile destination naming the tokens file is a
    typed ``logs_destination_credential:`` refusal and the bearer never
    reaches output (the R3 fold's twin coverage); (rung 2) with the
    pidfile ABSENT and a staged log, a POISONED tokens file — read_text
    raising on it — changes nothing: the tokens file is structurally
    never a destination candidate at rung 2."""
    bearer = _stage_tokens(bindings_file)
    _stage_twin_pidfile(bindings_file, str(lifecycle.tokens_path(bindings_file)))
    refused = CliRunner().invoke(
        cli, ["logs", str(starter_project), "--bindings", str(bindings_file)]
    )
    assert refused.exit_code == 1, _twins_combined(refused)
    assert "logs_destination_credential:" in _twins_combined(refused)
    assert bearer not in _twins_combined(refused)

    # Rung 2: no pidfile, a staged log, and a tokens file that explodes
    # on ANY read — the tail still completes.
    log = lifecycle.log_path(bindings_file)
    log.write_text("post-mortem line\n", encoding="utf-8")
    lifecycle.pid_path(bindings_file).unlink()
    real_read_text = Path.read_text

    def poisoned_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name.endswith(lifecycle.TOKENS_SUFFIX):
            raise OSError("poisoned tokens read — the twin never reads it")
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(Path, "read_text", poisoned_read_text)
    completed = CliRunner().invoke(
        cli, ["logs", str(starter_project), "--bindings", str(bindings_file)]
    )
    assert completed.exit_code == 0, _twins_combined(completed)
    payload = json.loads(completed.output)
    assert payload["lines"] == ["post-mortem line"]
    assert payload["post_mortem"] is True


def test_s9_doctor_stale_stop_request_passes_naming_start(
    bindings_file: Path,
) -> None:
    """S9: a stale <bindings>.stop request targeting a dead pid — the
    sidecars row passes with the note naming `start` as the cleaner (the
    R4 fold's fifth check); exit 0."""
    _stage_twin_pidfile(bindings_file, "stderr")
    dead = subprocess.Popen(
        [sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL
    )
    dead.wait(timeout=10)
    lifecycle.write_stop_request(
        bindings_file, actor_pid=4242, target_pid=dead.pid
    )
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert result.exit_code == 0, _twins_combined(result)
    row = _twin_row(result, "stop_request")
    assert row["verdict"] == "pass"
    assert "start" in str(row["detail"]), "the note names the cleaner verb"


@requires_posix_file_perms
def test_control_e_neutralized_tokens_perms_breaks_s6(
    bindings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED control (e): with the tokens-perms check neutralized, the S6
    scenario no longer produces its fail row — S6 would be red."""
    _stage_twin_pidfile(bindings_file, "stderr")
    _stage_tokens(bindings_file)
    lifecycle.tokens_path(bindings_file).chmod(0o644)
    monkeypatch.setattr(lifecycle, "_tokens_perms_problem", lambda path: None)
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert _twin_row(result, "tokens")["verdict"] != "fail"


# --- W1/W3/W4/W8: the fold-wave arms (the doctor + logs twins) ---------------------


def _stage_twin_giant_line(bindings_file: Path, size: int) -> Path:
    """A staged ``<bindings>.log`` whose ONLY line is ``size`` bytes with
    no newline — the blob shape the windowed tail must refuse, not dump."""
    log = lifecycle.log_path(bindings_file)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"x" * size)
    return log


def test_w1a_twin_giant_single_line_refuses_the_fifty_line_request(
    starter_project: Path, bindings_file: Path
) -> None:
    """W1 RED arm 1 (twin): a no-newline giant file (300 KiB single
    line) + ``--lines 50`` — the requested lines cannot be served within
    the windowed tail: a typed ``logs_window_cap:`` refusal, exit 1, and
    the blob's bytes never reach output."""
    log = _stage_twin_giant_line(bindings_file, 300 * 1024)
    _stage_twin_pidfile(bindings_file, str(log))
    result = CliRunner().invoke(
        cli,
        ["logs", str(starter_project), "--bindings", str(bindings_file),
         "--lines", "50"],
    )
    assert result.exit_code == 1, _twins_combined(result)
    assert "logs_window_cap:" in _twins_combined(result), _twins_combined(result)
    assert "x" * 100 not in _twins_combined(result), "the blob never reaches output"


def test_w1b_twin_dense_blob_refuses_within_one_doubling_cycle_of_the_cap(
    starter_project: Path, bindings_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1 RED arm 2 (twin): a dense 5 MiB no-newline file + ``--lines
    50`` — the refusal fires within one doubling cycle of the window cap
    (no single read past the cap; the cumulative reads stay under ``2 x``
    the cap)."""
    log = _stage_twin_giant_line(bindings_file, 5 * 1024 * 1024)
    _stage_twin_pidfile(bindings_file, str(log))
    reads: list[int] = []
    real_open = Path.open

    def counting_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        handle = real_open(self, *args, **kwargs)
        real_read = handle.read

        def counting_read(size: int = -1) -> bytes:
            data = real_read(size)
            reads.append(len(data))
            return cast(bytes, data)

        handle.read = counting_read
        return handle

    monkeypatch.setattr(Path, "open", counting_open)
    result = CliRunner().invoke(
        cli,
        ["logs", str(starter_project), "--bindings", str(bindings_file),
         "--lines", "50"],
    )
    assert result.exit_code == 1, _twins_combined(result)
    assert "logs_window_cap:" in _twins_combined(result), _twins_combined(result)
    assert reads, "the windowed tail read something"
    assert max(reads) <= lifecycle.TAIL_WINDOW_CAP_BYTES, max(reads)
    assert sum(reads) <= 2 * lifecycle.TAIL_WINDOW_CAP_BYTES, sum(reads)


def test_w3_twin_newline_terminated_unparseable_final_line_is_tampering(
    bindings_file: Path,
) -> None:
    """W3 (l2 F1, literal twin): a newline-terminated unparseable FINAL
    line is TAMPERING — a single-write+fsync append cannot end with its
    own newline — not the crash-tear pass: fail row, exit 1 (today the
    twin classifier calls any final line a crash tear and passes)."""
    journal = lifecycle.journal_path(bindings_file)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        '{"wall": "x"}\nGARBAGE-COMPLETE-LINE\n', encoding="utf-8"
    )
    _stage_twin_pidfile(bindings_file, "stderr")
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert result.exit_code == 1, _twins_combined(result)
    row = _twin_row(result, "journal")
    assert row["verdict"] == "fail", row
    assert "tamper" in str(row["detail"]).lower(), row


def test_w3_twin_unterminated_unparseable_final_line_stays_the_crash_tear(
    bindings_file: Path,
) -> None:
    """The crash-tear half (unchanged, twin): an UNTERMINATED unparseable
    final line is still the known tear shape — pass with the note."""
    journal = lifecycle.journal_path(bindings_file)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        '{"wall": "x"}\n{"wall": "2026-10-09T00:00:01Z", "even',
        encoding="utf-8",
    )
    _stage_twin_pidfile(bindings_file, "stderr")
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert result.exit_code == 0, _twins_combined(result)
    row = _twin_row(result, "journal")
    assert row["verdict"] == "pass", row
    assert "torn" in str(row["detail"]).lower(), row


@POSIX_ONLY
def test_w4a_twin_post_mortem_symlink_to_tokens_refuses(
    starter_project: Path, bindings_file: Path
) -> None:
    """W4 (a) twin: the post-mortem rung had NO credential guard — a
    ``<bindings>.log`` SYMLINK to ``<bindings>.tokens`` tailed the bearer
    (today it does). The guard now covers both rungs."""
    bearer = _stage_tokens(bindings_file)
    log = lifecycle.log_path(bindings_file)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.symlink_to(lifecycle.tokens_path(bindings_file))
    result = CliRunner().invoke(
        cli, ["logs", str(starter_project), "--bindings", str(bindings_file)]
    )
    assert result.exit_code == 1, _twins_combined(result)
    assert "logs_destination_credential:" in _twins_combined(result)
    assert bearer not in _twins_combined(result)


@POSIX_ONLY
def test_w4b_twin_post_mortem_hardlink_to_tokens_refuses(
    starter_project: Path, bindings_file: Path
) -> None:
    """W4 (b) twin: the compare is ``(st_dev, st_ino)`` after resolve — a
    HARDLINK of ``<bindings>.tokens`` (a different path, the same inode)
    is the same credential and is refused (today's path-equality compare
    misses it and the tail leaks the bearer)."""
    bearer = _stage_tokens(bindings_file)
    log = lifecycle.log_path(bindings_file)
    log.parent.mkdir(parents=True, exist_ok=True)
    os.link(lifecycle.tokens_path(bindings_file), log)
    result = CliRunner().invoke(
        cli, ["logs", str(starter_project), "--bindings", str(bindings_file)]
    )
    assert result.exit_code == 1, _twins_combined(result)
    assert "logs_destination_credential:" in _twins_combined(result)
    assert bearer not in _twins_combined(result)


def test_w8_twin_pid_not_ours_fails_and_unknown_exits_one(
    bindings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W8 (the twin pid legs, previously untested): a not-ours pidfile (a
    live pid whose recorded start time differs) → ``fail`` with
    ``supervision_stale_pid:``; ticks unobtainable → ``unknown`` with
    ``supervision_pid_unknown:`` and exit 1 (the unknown-exits-1
    contract)."""
    lifecycle.pid_path(bindings_file).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "server": "benchweave-sdk-server",
                "bindings": str(bindings_file),
                "started_wall": "2026-10-09T00:00:00Z",
                "started_ticks": (
                    lifecycle.process_start_ticks(os.getpid()) or 0
                ) + 1,
                "log_destination": "stderr",
                "schema": 1,
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert result.exit_code == 1, _twins_combined(result)
    row = _twin_row(result, "pid")
    assert row["verdict"] == "fail", row
    assert "supervision_stale_pid:" in str(row["detail"]), row
    # The unknown leg: ticks unobtainable on the live side.
    monkeypatch.setattr(lifecycle, "process_start_ticks", lambda pid: None)
    result = CliRunner().invoke(cli, ["doctor", "--bindings", str(bindings_file)])
    assert result.exit_code == 1, _twins_combined(result)
    row = _twin_row(result, "pid")
    assert row["verdict"] == "unknown", row
    assert "supervision_pid_unknown:" in str(row["detail"]), row
