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
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

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
