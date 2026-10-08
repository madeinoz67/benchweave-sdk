"""The SDK host's lifecycle twins (issue #422 increment 3).

The design authority is the gateway's supervision record
(``benchweave`` repo, ``.claude/deep-review/2026-10-08-issue422-
supervision-design.md`` §5): ONE standard, per-surface application. The
SDK serve is the twin's supervised surface — start/stop/restart/status,
a pidfile in the twin format, the wedge ladder (SIGTERM → bounded wait →
SIGKILL), audit rows in its own supervision file.

The recorded divergences from the gateway standard, each load-bearing
here: NO refusal machinery (nothing is ever at stake — no runs); NO
``--protective`` (no procedures, no store, no commissioned safe
transition — the flag does not exist on this CLI, pinned by the S3 help
enumeration arm); NO reconciliation gate (no store, nothing to
reconcile); ``service install`` REFUSED (a plugin-author preview server
is not a boot daemon). Everything else is the same doctrine.

The supervision family derives from the BINDINGS DOCUMENT path (the
state-file family the bindings document already follows — Decision 9's
precedent): ``<bindings>.pid`` / ``.stop`` / ``.log`` / ``.tokens`` /
``.supervision.jsonl`` as siblings of the resolved bindings file.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: The supervision file family's suffixes (siblings of the bindings file).
PID_SUFFIX = ".pid"
STOP_SUFFIX = ".stop"
LOG_SUFFIX = ".log"
TOKENS_SUFFIX = ".tokens"
JOURNAL_SUFFIX = ".supervision.jsonl"

#: The pidfile's shape version (the gateway twin's schema, its own file).
PIDFILE_SCHEMA = 1

_POSIX = sys.platform != "win32"

#: The CLI's verdict-wait bound (the daemon's poll cadence is ≤ 1 s).
VERDICT_WAIT_S = 15.0

#: The wedge ladder's bounded exit-wait before the SIGKILL rung (there is
#: no commissioned window to respect — no procedures — so this is a
#: service parameter, not a bench envelope).
WEDGE_WAIT_S = 30.0

#: The bounded exit-wait after the kill.
KILL_WINDOW_S = 30.0

#: ``start``'s readiness window (pidfile names the child).
START_READINESS_S = 30.0


class LifecycleError(RuntimeError):
    """A typed lifecycle refusal (the message carries the prefix)."""


# --- the family --------------------------------------------------------------------


def _resolved(bindings: Path) -> Path:
    return Path(bindings).resolve()


def pid_path(bindings: Path) -> Path:
    return _resolved(bindings).with_name(_resolved(bindings).name + PID_SUFFIX)


def stop_path(bindings: Path) -> Path:
    return _resolved(bindings).with_name(_resolved(bindings).name + STOP_SUFFIX)


def log_path(bindings: Path) -> Path:
    return _resolved(bindings).with_name(_resolved(bindings).name + LOG_SUFFIX)


def tokens_path(bindings: Path) -> Path:
    return _resolved(bindings).with_name(_resolved(bindings).name + TOKENS_SUFFIX)


def journal_path(bindings: Path) -> Path:
    return _resolved(bindings).with_name(_resolved(bindings).name + JOURNAL_SUFFIX)


def _now_wall() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


# --- process identity (the twin of the gateway's §2.4 lattice, no hold) -------------


def probe_process(pid: int) -> str:
    """``running`` / ``dead`` / ``unknown`` (EPERM reads running)."""
    if not _POSIX:
        return _probe_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "running"
    except OSError:
        return "unknown"
    return "running"


def _probe_windows(pid: int) -> str:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, 0, pid)
    if not handle:
        error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
        if error == 5:
            return "running"
        if error == 87:
            return "dead"
        return "unknown"
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return "running" if code.value == 259 else "dead"
        return "unknown"
    finally:
        kernel32.CloseHandle(handle)


def process_start_ticks(pid: int) -> int | None:
    """The OS process start time (opaque, comparable per platform)."""
    if sys.platform == "linux":
        return _ticks_linux(pid)
    if sys.platform == "darwin":
        return _ticks_darwin(pid)
    if sys.platform == "win32":
        return _ticks_windows(pid)
    return None


def _ticks_linux(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    tail = raw.rsplit(")", 1)
    if len(tail) != 2:
        return None
    fields = tail[1].split()
    if len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _ticks_darwin(pid: int) -> int | None:
    import ctypes
    import struct as _struct
    import time as _time

    libc = ctypes.CDLL(None, use_errno=True)
    sysctl = libc.sysctl
    sysctl.restype = ctypes.c_int
    mib = (ctypes.c_int * 4)(1, 14, 1, pid)
    buf = ctypes.create_string_buffer(1024)
    length = ctypes.c_size_t(len(buf))
    if sysctl(mib, 4, buf, ctypes.byref(length), None, 0) != 0:
        return None
    raw = buf.raw[: length.value]
    horizon = _time.time() - 30 * 86400
    for offset in range(0, max(0, len(raw) - 16), 8):
        sec, usec = _struct.unpack_from("<qI", raw, offset)
        if horizon <= sec <= _time.time() and 0 <= usec < 1_000_000:
            return int(sec) * 1_000_000 + int(usec)
    return None


def _ticks_windows(pid: int) -> int | None:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, 0, pid)
    if not handle:
        return None
    try:
        class _Filetime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

        creation = _Filetime()
        exit_ = _Filetime()
        kernel = _Filetime()
        user = _Filetime()
        ok = kernel32.GetProcessTimes(
            handle, ctypes.byref(creation), ctypes.byref(exit_),
            ctypes.byref(kernel), ctypes.byref(user),
        )
        if not ok:
            return None
        return (int(creation.high) << 32) | int(creation.low)
    finally:
        kernel32.CloseHandle(handle)


def write_pidfile(bindings: Path, *, log_destination: str) -> dict[str, Any]:
    """The twin pidfile (no gateway_id/hold: this surface owns nothing but
    itself)."""
    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "server": "benchweave-sdk-server",
        "bindings": str(_resolved(bindings)),
        "started_wall": _now_wall(),
        "started_ticks": process_start_ticks(os.getpid()),
        "log_destination": log_destination,
        "schema": PIDFILE_SCHEMA,
    }
    _atomic_write_json(pid_path(bindings), payload)
    return payload


def read_pidfile(bindings: Path) -> dict[str, Any] | None:
    try:
        raw = pid_path(bindings).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("pid"), int):
        return parsed
    return None


def remove_pidfile(bindings: Path) -> None:
    with contextlib.suppress(OSError):
        pid_path(bindings).unlink()


def verify_identity(bindings: Path) -> str:
    """The twin lattice, SIMPLER than the gateway's: no store hold exists
    to vouch or desync, so ``ours`` requires probe + start-time match;
    ticks unobtainable is a REFUSAL (unknown — the conservative
    direction; there is no hold to defer to)."""
    record = read_pidfile(bindings)
    if record is None:
        return "absent"
    pid = int(record["pid"])
    liveness = probe_process(pid)
    if liveness == "dead":
        return "dead"
    if liveness == "unknown":
        return "unknown"
    ticks = process_start_ticks(pid)
    recorded = record.get("started_ticks")
    if ticks is None or not isinstance(recorded, int) or recorded != ticks:
        return "not-ours" if ticks is not None else "unknown"
    return "ours"


# --- the doorbell (twin: no refusal, no modes beyond stop) --------------------------


def write_stop_request(bindings: Path, *, actor_pid: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "mode": "stop",
        "requested_wall": _now_wall(),
        "actor_pid": actor_pid,
    }
    _atomic_write_json(stop_path(bindings), payload)
    return payload


def read_stop_file(bindings: Path) -> dict[str, Any] | None:
    try:
        raw = stop_path(bindings).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def answer_stop_request(bindings: Path) -> bool:
    """Consume ONE unconsumed stop request (the daemon-side twin): rewrite
    the file into the accepted verdict — the SDK host has no refusal
    machinery (nothing is at stake), so acceptance is the only verdict —
    and return True when a request was consumed."""
    record = read_stop_file(bindings)
    if record is None or "status" in record:
        return False
    _atomic_write_json(
        stop_path(bindings),
        {
            "schema": 1,
            "status": "accepted",
            "mode": "stop",
            "decided_wall": _now_wall(),
            "server_pid": os.getpid(),
        },
    )
    return True


def journal_append(bindings: Path, event: str, **fields: Any) -> None:
    row: dict[str, Any] = {"wall": _now_wall(), "event": event, **fields}
    payload = (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(journal_path(bindings), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


# --- the verbs ----------------------------------------------------------------------


def stop(bindings: Path) -> dict[str, Any]:
    """The twin stop: doorbell + SIGTERM → bounded exit-wait → one audited
    SIGKILL (the wedge ladder — no rung 2 exists by construction: no
    runs). A wedged host is killed and disclosed non-zero."""
    verdict = verify_identity(bindings)
    if verdict == "absent":
        journal_append(bindings, "stop_noop", reason="no pidfile")
        return {"stopped": False, "status": "not_running"}
    if verdict == "dead":
        remove_pidfile(bindings)
        with contextlib.suppress(OSError):
            stop_path(bindings).unlink()
        journal_append(bindings, "stale_sidecars_cleared")
        return {"stopped": False, "status": "not running (cleared stale sidecars)"}
    if verdict != "ours":
        detail = (
            "supervision_stale_pid: the pidfile names a process that is not "
            "this host" if verdict == "not-ours" else
            "supervision_pid_unknown: the pidfile's process could not be "
            "verified"
        )
        raise LifecycleError(f"{detail} ({pid_path(bindings)}); nothing was signaled")

    record = read_pidfile(bindings)
    pid = int((record or {}).get("pid", 0))
    write_stop_request(bindings, actor_pid=os.getpid())
    signal_name = "file-poll-only"
    if _POSIX:
        os.kill(pid, signal.SIGTERM)
        signal_name = "SIGTERM"
    journal_append(
        bindings, "stop_requested", target_pid=pid, signal_name=signal_name
    )
    # The doorbell is LOAD-BEARING on every platform (on Windows it is the
    # only channel; on POSIX it races the signal): observe the daemon's
    # OWN consumption — the request rewritten into an accepted verdict —
    # within the verdict window. A daemon that exits before consuming
    # (the signal won the race outright) is still stopped, and the report
    # says which path won instead of asserting the file was read.
    verdict_status = "unobserved"
    verdict_deadline = time.monotonic() + VERDICT_WAIT_S
    while time.monotonic() < verdict_deadline:
        stop_record = read_stop_file(bindings)
        if stop_record is not None and "status" in stop_record:
            verdict_status = str(stop_record.get("status"))
            break
        if _exited(pid):
            break
        time.sleep(0.2)
    deadline = time.monotonic() + WEDGE_WAIT_S
    while time.monotonic() < deadline:
        if _exited(pid) or not pid_path(bindings).exists():
            journal_append(bindings, "stopped", mode="stop", verdict=verdict_status)
            return {
                "stopped": True,
                "status": "accepted",
                "pid": pid,
                "verdict": verdict_status,
            }
        time.sleep(0.2)
    # The wedge ladder's last rung: the intent row BEFORE the kill (the
    # gateway twin's F9 ordering), one SIGKILL, a bounded exit-wait, and a
    # non-zero exit that discloses the kill.
    journal_append(
        bindings, "sigkill_sent", target_pid=pid, reason="wedge_wait_exceeded"
    )
    if _POSIX:
        os.kill(pid, signal.SIGKILL)
    kill_deadline = time.monotonic() + KILL_WINDOW_S
    while time.monotonic() < kill_deadline and not _exited(pid):
        time.sleep(0.2)
    still = not _exited(pid)
    raise LifecycleError(
        "supervision_sigkill: the host did not exit within "
        f"{WEDGE_WAIT_S:.0f}s of the stop (wedge_wait_exceeded); the CLI "
        f"sent SIGKILL to pid {pid}"
        + ("; the process is STILL ALIVE" if still else "")
    )


def start(
    project: Path,
    *,
    bindings: Path,
    host: str,
    port: int,
    transport: str,
    device: str | None,
    scenario: str | None,
) -> dict[str, Any]:
    """The twin start: pre-spawn gate (an OURS pidfile refuses), detached
    spawn with stderr to ``<bindings>.log``, hold-free readiness (the
    pidfile names the child) with liveness polling and the end-of-wait
    re-check."""
    verdict = verify_identity(bindings)
    if verdict == "ours":
        record = read_pidfile(bindings) or {}
        raise LifecycleError(
            "supervision_already_running: the pidfile verifies pid "
            f"{record.get('pid')} as this host ({pid_path(bindings)})"
        )
    if verdict in ("unknown",):
        raise LifecycleError(
            "supervision_pid_unknown: the pidfile's process could not be "
            f"verified ({pid_path(bindings)}); nothing was signaled"
        )
    log = log_path(bindings)
    journal_append(bindings, "start_requested", host=host, port=port, log=str(log))
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    argv = [
        sys.executable, "-m", "benchweave_sdk_server.cli", "serve", str(project),
        "--host", host, "--port", str(port),
        "--transport", transport,
        "--no-open",
        "--supervised",
    ]
    if device is not None:
        argv += ["--device", device]
    if scenario is not None:
        argv += ["--scenario", scenario]
    env = os.environ.copy()
    # The family anchor rides the ENV, never the flag: ``--bindings`` is
    # serial-only on the serve surface (one flag one meaning), while the
    # supervision family anchors beside the bindings document on every
    # transport.
    env["BENCHWEAVE_STANDALONE_BINDINGS"] = str(_resolved(bindings))
    env["BENCHWEAVE_SDK_LOG_DESTINATION"] = str(log)
    try:
        proc = subprocess.Popen(  # noqa: S603 — fixed argv, this interpreter
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=handle,
            env=env,
        )
    finally:
        os.close(handle)
    deadline = time.monotonic() + START_READINESS_S
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                journal_append(bindings, "start_failed", pid=proc.pid,
                               rc=proc.returncode)
                raise LifecycleError(
                    f"start_failed: the serve child exited rc="
                    f"{proc.returncode} before readiness; log tail: "
                    f"{_log_tail(log)}"
                )
            fresh = read_pidfile(bindings)
            if fresh is not None and int(fresh["pid"]) == proc.pid:
                record = fresh
                if proc.poll() is not None:
                    raise LifecycleError(
                        "start_failed: the child died immediately after "
                        f"writing its pidfile (rc={proc.returncode}); log "
                        f"tail: {_log_tail(log)}"
                    )
                journal_append(bindings, "started", pid=proc.pid)
                return {
                    "started": True,
                    "pid": proc.pid,
                    "log": str(log),
                    "tokens": str(tokens_path(bindings)),
                    "host": host,
                    "port": port,
                }
            time.sleep(0.2)
        journal_append(bindings, "start_failed", pid=proc.pid, rc=None)
        raise LifecycleError(
            f"start_failed: no readiness within {START_READINESS_S:.0f}s; "
            f"log tail: {_log_tail(log)}"
        )
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        raise


def restart(
    project: Path,
    *,
    bindings: Path,
    host: str,
    port: int,
    transport: str,
    device: str | None,
    scenario: str | None,
) -> dict[str, Any]:
    stopped = stop(bindings)
    started = start(
        project, bindings=bindings, host=host, port=port, transport=transport,
        device=device, scenario=scenario,
    )
    return {"stopped": stopped, "started": started}


def status(bindings: Path) -> dict[str, Any]:
    record = read_pidfile(bindings)
    return {
        "bindings": str(_resolved(bindings)),
        "pid": {
            "verdict": verify_identity(bindings),
            "pid": (record or {}).get("pid"),
        },
        "log_destination": (record or {}).get("log_destination"),
        "tokens_file": str(tokens_path(bindings)),
    }


def _log_tail(path: Path, size: int = 2000) -> str:
    try:
        return path.read_text(errors="replace")[-size:].strip() or "(empty)"
    except OSError:
        return "(unreadable)"


def _exited(pid: int) -> bool:
    """Exit detection that survives the unreaped child: probe first, then
    (POSIX) a non-blocking waitpid — a ZOMBIE we own reaps here and reads
    exited; a pid that is not our child falls back to the probe alone."""
    if probe_process(pid) != "running":
        return True
    if _POSIX:
        try:
            waited, _ = os.waitpid(pid, os.WNOHANG)
            return waited != 0
        except ChildProcessError:
            return False
        except OSError:
            return False
    return False


# --- the token delivery file (F5 fold: the ONE credential-carrying exception) -------


def deliver_tokens(
    bindings: Path,
    *,
    bearer_token: str,
    operator_action_token: str | None,
    host: str,
    port: int,
) -> Path:
    """Write the per-launch tokens to a 0600 sibling of the bindings file.

    The gateway record's F5 fold: SDK serve prints per-launch bearer
    tokens to stdout, so a STARTED spawn (stdout devnull'd, stderr into
    ``<bindings>.log``) would destroy them in devnull or leak them into
    the log. The file is the one documented credential-carrying exception
    in the family's orbit, and ``logs`` never displays it. This write
    FAILS LOUDLY: a token file that cannot be protected (a FAT volume has
    no access lists) refuses rather than writing an unprotected
    credential."""
    payload = {
        "pid": os.getpid(),
        "bearer_token": bearer_token,
        "url": f"http://{host}:{port}",
        "written_wall": _now_wall(),
    }
    if operator_action_token is not None:
        payload["operator_action_token"] = operator_action_token
        payload["operator_action_url"] = (
            f"http://{host}:{port}/?operator_action={operator_action_token}"
        )
    path = tokens_path(bindings)
    _atomic_write_json(path, payload)
    if sys.platform == "win32":
        _restrict_windows(path)
    return path


def _restrict_windows(path: Path) -> None:
    """Fail-closed ACL restriction (the credential exception's posture)."""
    import csv
    import re
    import subprocess as _subprocess

    sid_pattern = re.compile(r"S-1-[0-9]+(?:-[0-9]+)+")
    system32 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
    try:
        identity = _subprocess.run(  # noqa: S603 — fixed argv, absolute path
            [str(system32 / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, check=False, timeout=30,
        )
        row = next(csv.reader(identity.stdout.splitlines()), [])
        sid = row[-1].strip() if row else ""
        if identity.returncode != 0 or sid_pattern.fullmatch(sid) is None:
            raise LifecycleError(
                f"cannot protect {path}: the current user's SID was unreadable — "
                "no token file was written"
            )
        restricted = _subprocess.run(  # noqa: S603 — fixed argv, absolute path
            [str(system32 / "icacls.exe"), str(path),
             "/inheritance:r", "/grant:r", f"*{sid}:F"],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, _subprocess.TimeoutExpired) as error:
        raise LifecycleError(f"cannot protect {path}: {error}") from error
    if restricted.returncode != 0:
        detail = (restricted.stderr or restricted.stdout).strip().splitlines()
        raise LifecycleError(
            f"cannot restrict {path} to the current user, so no token file "
            "was written" + (f": {detail[0]}" if detail else "")
        )
