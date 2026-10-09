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

#: The win32 daemon creationflags — the ``start_new_session`` twin (see
#: ``start``). Defined as literals because a POSIX ``subprocess`` module
#: does not carry them (they exist only under CPython's Windows build);
#: the values are the frozen Win32 API constants ``subprocess`` itself
#: defines there: DETACHED_PROCESS 0x8, CREATE_NEW_PROCESS_GROUP 0x200.
_WIN32_DETACHED_PROCESS = 0x00000008
_WIN32_CREATE_NEW_PROCESS_GROUP = 0x00000200

#: The CLI's verdict-wait bound (the daemon's poll cadence is ≤ 1 s).
VERDICT_WAIT_S = 15.0

#: The serve config's explicit connection-drain bound (S2, the gateway's
#: F2 twin): uvicorn's default (`None`) waits for open connections
#: forever, and one open /events tab would hang every stop into the kill
#: rung. There is no commissioned window to respect on this surface (no
#: procedures), so this is a service parameter — deliberately INSIDE the
#: wedge wait so a healthy drain always beats the escalation rung.
#: (int: uvicorn's Config types the field int | None.)
GRACEFUL_TIMEOUT_S = 10

#: The wedge ladder's bounded exit-wait before the SIGKILL rung (there is
#: no commissioned window to respect — no procedures — so this is a
#: service parameter, not a bench envelope).
WEDGE_WAIT_S = 30.0

#: The bounded exit-wait after the kill.
KILL_WINDOW_S = 30.0

#: ``start``'s readiness window (pidfile names the child).
START_READINESS_S = 30.0

#: The Windows tokens-protection consults' per-call budget (whoami, then
#: icacls). Both run in the child's PRE-readiness path, so the combined
#: budget must fit INSIDE ``START_READINESS_S``: a stuck consult whose own
#: timeout exceeds the parent's readiness window is structurally
#: unwitnessable — the parent times out with an empty log tail while the
#: child sits silently inside its own bounded wait (the windows CI shape
#: ``start_failed: no readiness within 30s; log tail: (empty)``). At the
#: previous 30 s per call, 2 x 30 > 30 was exactly that defect.
_ACL_CONSULT_TIMEOUT_S = 10.0


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

    if not hasattr(ctypes, "WinDLL"):
        # A simulated win32 platform on a POSIX host (the test seam):
        # there is no WinDLL to consult — indeterminate, never a crash.
        return "unknown"
    # use_last_error is LOAD-BEARING (S6): ctypes.get_last_error() reads
    # the swap slot only a WinDLL created with the flag maintains — the
    # cached windll instance leaves it at 0, and every OpenProcess
    # failure misreads "unknown" (the dead(87)/running(5) classes never
    # fire).
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, 0, pid)
    if not handle:
        get_last_error = getattr(ctypes, "get_last_error", lambda: 0)
        error = int(get_last_error())
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
    """``sysctl(KERN_PROC_PID)`` → ``kp_proc.p_starttime`` (§2.4).

    Disclosed horizon (S7): the plausible-start scan accepts a seconds
    value within the LAST 30 DAYS — a process started longer ago than
    that reads ``None`` (unknown identity, the conservative direction),
    never a wrong match. The 30-day figure matches the longest plausible
    preview-server uptime an author leaves running; raising it widens
    the false-match window, lowering it strands long-lived hosts.
    """
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

    if not hasattr(ctypes, "WinDLL"):
        return None  # the simulated-win32 seam (see _probe_windows)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # S6
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
    ticks unobtainable on EITHER side (the live read or the pidfile's
    own recorded value) is a REFUSAL (unknown — the conservative
    direction; there is no hold to defer to). S3: a null RECORDED value
    with an obtainable live read is the same unresolvable comparison —
    unknown, never `not-ours` (a pidfile written where ticks were
    unreadable is not evidence of a recycled pid)."""
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
    if ticks is None or not isinstance(recorded, int):
        return "unknown"
    if recorded != ticks:
        return "not-ours"
    return "ours"


# --- the doorbell (twin: no refusal, no modes beyond stop) --------------------------


def write_stop_request(
    bindings: Path, *, actor_pid: int, target_pid: int | None = None
) -> dict[str, Any]:
    """Write the stop REQUEST atomically (doorbell step 1).

    ``mode`` is the gateway vocabulary's ``plain`` (S4: `stop` names the
    VERB, never the mode — twin consistency with the one standard).
    ``target_pid`` era-binds the request to its target launch (S1): the
    daemon consumes only requests naming its own pid, and ``start``
    clears unconsumed leftovers before spawning — a request a dead
    launch never consumed can never stop the next one (the
    stale-request suicide).
    """
    payload: dict[str, Any] = {
        "schema": 1,
        "mode": "plain",
        "requested_wall": _now_wall(),
        "actor_pid": actor_pid,
    }
    if target_pid is not None:
        payload["target_pid"] = int(target_pid)
    _atomic_write_json(stop_path(bindings), payload)
    return payload


def stop_request_is_bound_to(record: dict[str, Any], pid: int) -> bool:
    """S1's era rule: the request is this launch's to consume only when
    it names this pid. An unbound (legacy or hand-written) request is
    NOT bound to this launch — the operator's next ``stop`` writes a
    bound one; refusing is the conservative direction."""
    target = record.get("target_pid")
    return isinstance(target, int) and target == pid


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


def answer_stop_request(bindings: Path, *, daemon_pid: int | None = None) -> bool:
    """Consume ONE unconsumed stop request (the daemon-side twin): rewrite
    the file into the accepted verdict — the SDK host has no refusal
    machinery (nothing is at stake), so acceptance is the only verdict —
    and return True when a request was consumed.

    S1's era rule: a request that does not name THIS launch is never
    consumed (left exactly as it is; `start` clears it, the operator's
    next `stop` writes a bound one). S4: the daemon writes NO journal
    row here — the verdict file carries the fields and the CLI (the
    journal's one writer) journals them on observation.
    """
    record = read_stop_file(bindings)
    if record is None or "status" in record:
        return False
    pid = os.getpid() if daemon_pid is None else daemon_pid
    if not stop_request_is_bound_to(record, pid):
        return False
    _atomic_write_json(
        stop_path(bindings),
        {
            "schema": 1,
            "status": "accepted",
            "mode": "plain",
            "decided_wall": _now_wall(),
            "server_pid": pid,
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

    def _unwritable(error: OSError, path: Path) -> LifecycleError:
        # S5: a family the operator cannot write (a read-only parent) is
        # a TYPED refusal — never a raw PermissionError traceback.
        return LifecycleError(
            f"supervision_refused_unwritable: cannot write {path} "
            f"({error}) — the supervision family's parent is not "
            "writable by this user; nothing was signaled"
        )

    def _journal(event: str, **fields: Any) -> None:
        try:
            journal_append(bindings, event, **fields)
        except OSError as error:
            raise _unwritable(error, journal_path(bindings)) from error

    verdict = verify_identity(bindings)
    if verdict == "absent":
        _journal("stop_noop", reason="no pidfile")
        return {"stopped": False, "status": "not_running"}
    if verdict == "dead":
        remove_pidfile(bindings)
        with contextlib.suppress(OSError):
            stop_path(bindings).unlink()
        _journal("stale_sidecars_cleared")
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
    try:
        write_stop_request(
            bindings, actor_pid=os.getpid(), target_pid=pid
        )
    except OSError as error:
        raise _unwritable(error, stop_path(bindings)) from error
    signal_name = "file-poll-only"
    if _POSIX:
        os.kill(pid, signal.SIGTERM)
        signal_name = "SIGTERM"
    _journal("stop_requested", target_pid=pid, signal_name=signal_name)
    # The doorbell is LOAD-BEARING on every platform (on Windows it is the
    # only channel; on POSIX it races the signal): observe the daemon's
    # OWN consumption — the request rewritten into an accepted verdict —
    # within the verdict window. A daemon that exits before consuming
    # (the signal won the race outright) is still stopped, and the report
    # says which path won instead of asserting the file was read.
    #
    # S2 disclosure: this verdict-wait BURNS INSIDE the later wedge wait
    # (the exit window below starts only after it closes) — a daemon that
    # never answers the doorbell costs VERDICT_WAIT_S + WEDGE_WAIT_S
    # before the kill rung, by design (the file consumption is the thing
    # the ladder audits; skipping the wait would assert it was read).
    verdict_status = "unobserved"
    verdict_record: dict[str, Any] | None = None
    verdict_deadline = time.monotonic() + VERDICT_WAIT_S
    while time.monotonic() < verdict_deadline:
        stop_record = read_stop_file(bindings)
        if stop_record is not None and "status" in stop_record:
            verdict_status = str(stop_record.get("status"))
            verdict_record = stop_record
            break
        if _exited(pid):
            break
        time.sleep(0.2)
    if verdict_record is not None:
        # S4: the CLI is the journal's ONE writer — the daemon's
        # consumption reaches the journal here, as an observation
        # carrying the verdict file's own fields.
        _journal(
            "stop_consumed",
            server_pid=verdict_record.get("server_pid"),
            decided_wall=verdict_record.get("decided_wall"),
        )
    deadline = time.monotonic() + WEDGE_WAIT_S
    while time.monotonic() < deadline:
        if _exited(pid) or not pid_path(bindings).exists():
            _journal("stopped", mode="plain", verdict=verdict_status)
            return {
                "stopped": True,
                "status": "accepted",
                "pid": pid,
                "verdict": verdict_status,
            }
        time.sleep(0.2)
    # The wedge ladder's last rung: the intent row BEFORE the kill (the
    # gateway twin's F9 ordering), one kill (G6's twin discipline: POSIX
    # SIGKILL, Windows os.kill(pid, 9) → TerminateProcess — SENT on every
    # platform, and the row's signal field names what went out), a
    # bounded exit-wait, and a non-zero exit that discloses the kill.
    kill_signal = "TerminateProcess" if sys.platform == "win32" else "SIGKILL"
    with contextlib.suppress(OSError):
        # F9's proceed-on-failure ordering: the intent row is written
        # BEFORE the kill and a failed append must not skip the kill (the
        # disclosure rides the non-zero exit instead).
        journal_append(
            bindings,
            "sigkill_sent",
            target_pid=pid,
            reason="wedge_wait_exceeded",
            signal_name=kill_signal,
        )
    if sys.platform == "win32":
        os.kill(pid, 9)  # TerminateProcess — the capability exists (G6 twin)
    else:
        os.kill(pid, signal.SIGKILL)
    kill_deadline = time.monotonic() + KILL_WINDOW_S
    while time.monotonic() < kill_deadline and not _exited(pid):
        time.sleep(0.2)
    still = not _exited(pid)
    raise LifecycleError(
        "supervision_sigkill: the host did not exit within "
        f"{WEDGE_WAIT_S:.0f}s of the stop (wedge_wait_exceeded); the CLI "
        f"sent {kill_signal} to pid {pid}"
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
    stale = read_stop_file(bindings)
    if stale is not None and "status" not in stale:
        # S1's era binding, the start leg: a request a dead launch never
        # consumed is not the next launch's to honor — clear it (typed
        # journal note) so the boot is clean; a stale VERDICT is not a
        # request and stays (the next stop's request write replaces it).
        with contextlib.suppress(OSError):
            stop_path(bindings).unlink()
        journal_append(
            bindings,
            "stale_stop_request_cleared",
            target_pid=stale.get("target_pid"),
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
    # The detachment is platform-split: CPython SILENTLY IGNORES
    # ``start_new_session`` on win32 (the Windows ``_execute_child``
    # receives it as ``unused_start_new_session``), so the unconditional
    # kwarg claimed a detachment that did not exist there — the child
    # shared the parent's console and process group. The Windows twin is
    # the conventional daemon pair: DETACHED_PROCESS (no console) |
    # CREATE_NEW_PROCESS_GROUP (isolated from the parent's ctrl events).
    spawn_kwargs: dict[str, Any] = {}
    if _POSIX:
        spawn_kwargs["start_new_session"] = True
    else:
        spawn_kwargs["creationflags"] = (
            _WIN32_DETACHED_PROCESS | _WIN32_CREATE_NEW_PROCESS_GROUP
        )
    try:
        proc = subprocess.Popen(  # noqa: S603 — fixed argv, this interpreter
            argv,
            stdout=subprocess.DEVNULL,
            stderr=handle,
            env=env,
            **spawn_kwargs,
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
    if sys.platform != "win32":  # mypy narrows this; _POSIX does not
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
            capture_output=True, text=True, check=False,
            timeout=_ACL_CONSULT_TIMEOUT_S,
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
            capture_output=True, text=True, check=False,
            timeout=_ACL_CONSULT_TIMEOUT_S,
        )
    except (OSError, _subprocess.TimeoutExpired) as error:
        raise LifecycleError(f"cannot protect {path}: {error}") from error
    if restricted.returncode != 0:
        detail = (restricted.stderr or restricted.stdout).strip().splitlines()
        raise LifecycleError(
            f"cannot restrict {path} to the current user, so no token file "
            "was written" + (f": {detail[0]}" if detail else "")
        )


# --- the doctor + logs twins (issue #422 increment 4) ------------------------------
#
# One standard, per-surface application (the gateway record's §3): five
# typed doctor checks over the twin family, the logs twin with the same
# credential guard (the tokens file), and the same exit contract — 0 iff
# no fail and no unknown row. The recorded divergences from the gateway
# twin stand: no store/hold/env/unit checks (nothing to probe here), and
# NO journal leg in logs (``service install`` is refused on this surface,
# so no unit name exists to query).


#: Typed refusal prefixes — the greppable discipline, shared vocabulary
#: with the gateway's ``cli/diagnose.py``.
LOGS_LINES_DOMAIN = "logs_lines_domain:"
LOGS_DESTINATION_CREDENTIAL = "logs_destination_credential:"
LOGS_DESTINATION_STDERR = "logs_destination_stderr:"
LOGS_UNREADABLE = "logs_unreadable:"
LOGS_NO_DESTINATION = "logs_no_destination:"

#: The tail's first read window (a service parameter like the gateway's,
#: never a bench envelope — A02).
TAIL_WINDOW_BYTES = 64 * 1024


def _twin_row(check: str, verdict: str, detail: str,
              **fields: Any) -> dict[str, Any]:
    return {"check": check, "verdict": verdict, "detail": detail, **fields}


def _tokens_perms_problem(path: Path) -> str | None:
    """The 0600 discipline for the family's ONE credential-carrying
    member (the whole reason the tokens check exists on this surface):
    group/other access refuses. Windows is the skip-with-disclosure
    posture (mode bits do not reach the ACL; ``deliver_tokens``
    restricts the list at write time — the atrest #137 analogue)."""
    if sys.platform == "win32":
        return None
    mode = path.stat().st_mode
    if mode & 0o077:
        return (
            f"the tokens file mode {mode & 0o7777:o} allows group or other "
            "access — the file carries a live bearer token; restrict it "
            "to the owner (chmod 0600)"
        )
    return None


def _journal_problems(path: Path) -> tuple[list[str], list[str]]:
    """The journal parseability rule (the gateway D7 twin): a torn FINAL
    line is the crash-tear shape (a NOTE); an unparseable non-final line
    is only reachable by tampering (a problem); an unreadable journal is
    the ``supervision_journal_unreadable:`` problem the caller maps to
    ``unknown``."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return ([f"supervision_journal_unreadable: cannot read it: {error}"], [])
    lines = raw.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    problems: list[str] = []
    notes: list[str] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                notes.append(
                    "the journal's final line is torn — the known crash-tear "
                    "shape (appends are single-write+fsync)"
                )
            else:
                problems.append(
                    f"the journal's line {index + 1} is unparseable — "
                    "mid-file tears cannot occur by construction, so this "
                    "is tampering"
                )
    return (problems, notes)


def _doctor_pid_row(verdict: str, record: dict[str, Any] | None,
                    bindings: Path) -> dict[str, Any]:
    if verdict == "not-ours":
        return _twin_row(
            "pid", "fail",
            "supervision_stale_pid: the pidfile names a process that is "
            f"not this host ({pid_path(bindings)}); nothing was signaled",
            pid=(record or {}).get("pid"),
        )
    if verdict == "unknown":
        return _twin_row(
            "pid", "unknown",
            "supervision_pid_unknown: the pidfile's process could not be "
            "verified (start time unobtainable on either side of the "
            "comparison; there is no hold to vouch) — verify before acting",
            pid=(record or {}).get("pid"),
        )
    notes = {
        "ours": "running (ours)",
        "absent": (
            "no pidfile — never served or cleanly stopped (foreground "
            "serve writes a PRESENT stderr pidfile; a fresh `start` inside "
            "its ≤30 s readiness window can transiently read absent)"
        ),
        "dead": (
            "the pidfile names a dead pid — stale sidecars present; "
            "`stop` clears them"
        ),
    }
    return _twin_row("pid", "pass", notes.get(verdict, verdict),
                     pid=(record or {}).get("pid"))


def _doctor_log_row(verdict: str, record: dict[str, Any] | None,
                    bindings: Path) -> dict[str, Any]:
    raw = (record or {}).get("log_destination")
    if verdict != "absent" and record is not None:
        if raw == "stderr":
            return _twin_row(
                "log_destination", "pass",
                "stderr (foreground serve) — `logs` will refuse",
                destination="stderr",
            )
        if isinstance(raw, str) and raw:
            path = Path(raw)
            if path.is_file():
                return _twin_row("log_destination", "pass",
                                 f"the file {path}", destination=str(path))
            return _twin_row(
                "log_destination", "pass",
                f"no file at {path} yet — created at the next `start`",
                destination=str(path),
            )
        return _twin_row(
            "log_destination", "unknown",
            "the pidfile's log_destination is out-of-vocab "
            f"({raw!r}) — hand-written or tampered; verify before acting",
            destination=raw if isinstance(raw, str) else None,
        )
    log = log_path(bindings)
    if log.is_file():
        return _twin_row(
            "log_destination", "pass",
            f"no pidfile — the sibling {log} is the post-mortem source",
            destination=str(log), post_mortem=True,
        )
    return _twin_row(
        "log_destination", "pass",
        "no destination yet — <bindings>.log is created at the next `start`",
    )


def _doctor_tokens_row(bindings: Path) -> dict[str, Any]:
    path = tokens_path(bindings)
    if not path.is_file():
        return _twin_row(
            "tokens", "pass",
            "no tokens file — none delivered (not started, or foreground "
            "mode prints them to the terminal)",
        )
    problem = _tokens_perms_problem(path)
    if problem is not None:
        return _twin_row("tokens", "fail", problem)
    note = (
        "0600 (the family's one credential-carrying member; the bearer "
        "value never reaches output"
    )
    if sys.platform == "win32":
        note += (
            "; Windows: mode bits do not reach the ACL — deliver_tokens "
            "restricts the list at write time"
        )
    note += ")"
    return _twin_row("tokens", "pass", note)


def _doctor_journal_row(bindings: Path) -> dict[str, Any]:
    path = journal_path(bindings)
    if not path.is_file():
        return _twin_row("journal", "pass", "no journal yet")
    problems, notes = _journal_problems(path)
    details = notes + problems
    hard = [
        problem for problem in problems
        if not problem.startswith("supervision_journal_unreadable:")
    ]
    if hard:
        return _twin_row("journal", "fail", "; ".join(details) or "unparseable")
    if len(hard) != len(problems):
        return _twin_row("journal", "unknown", "; ".join(details))
    if not details:
        details = ["the journal's lines all parse"]
    return _twin_row("journal", "pass", "; ".join(details))


def _doctor_stop_row(bindings: Path) -> dict[str, Any]:
    path = stop_path(bindings)
    if not path.is_file():
        return _twin_row("stop_request", "pass", "no stop request present")
    record = read_stop_file(bindings)
    if record is None:
        return _twin_row(
            "stop_request", "pass",
            "the .stop file is unreadable or unparseable — inert "
            "daemon-side (the host's stop-check treats an unreadable "
            "request as no request)",
        )
    if "status" in record:
        return _twin_row("stop_request", "pass",
                         "the .stop file is a consumed verdict — inert")
    target = record.get("target_pid")
    if not isinstance(target, int):
        return _twin_row(
            "stop_request", "pass",
            "an unbound (legacy) stop request — `start` clears "
            "unconsumed requests",
        )
    if probe_process(target) == "dead":
        return _twin_row(
            "stop_request", "pass",
            f"a stale stop request targeting dead pid {target} — `start` "
            "clears unconsumed requests (era-bound, inert)",
        )
    return _twin_row(
        "stop_request", "pass",
        f"a stop request targeting live pid {target} — in flight or left "
        "over; inert unless its target consumes it",
    )


def doctor(bindings: Path) -> dict[str, Any]:
    """The five-check triage twin: ``{"bindings", "ok", "checks"}``.

    ``ok`` is no-fail AND no-unknown, the gateway's exit contract (fork
    F1's twin: ``not-ours`` fails, ``unknown`` is unknown/exit 1)."""
    bindings = _resolved(bindings)
    record = read_pidfile(bindings)
    verdict = verify_identity(bindings)
    rows = [
        _doctor_pid_row(verdict, record, bindings),
        _doctor_log_row(verdict, record, bindings),
        _doctor_tokens_row(bindings),
        _doctor_journal_row(bindings),
        _doctor_stop_row(bindings),
    ]
    ok = all(row["verdict"] == "pass" for row in rows)
    return {"bindings": str(bindings), "ok": ok, "checks": rows}


def _tail_lines(path: Path, lines: int) -> list[str]:
    """The seek-bounded windowed tail (the gateway twin's shape): read
    from ``max(0, size - 64 KiB)``, doubling on undercount — never a
    whole-file read; decode ``errors="replace"``."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        window = TAIL_WINDOW_BYTES
        while True:
            offset = max(0, size - window)
            handle.seek(offset)
            text = handle.read().decode("utf-8", errors="replace")
            rows = text.split("\n")
            if offset > 0 and rows:
                rows = rows[1:]  # the leading partial line at a mid-file seek
            if rows and rows[-1] == "":
                rows.pop()  # the final newline's empty remainder
            if len(rows) >= lines or offset == 0:
                return rows[-lines:]
            window *= 2


def logs(bindings: Path, lines: int) -> dict[str, Any]:
    """The logs twin (§3): pidfile ``log_destination`` path → the
    credential guard FIRST (a resolved destination equal to
    ``<bindings>.tokens`` is a typed refusal — the field is
    operator-steerable through ``BENCHWEAVE_SDK_LOG_DESTINATION``), then
    the windowed tail; ``"stderr"`` → typed refusal (no journal leg on
    this surface — ``service install`` is refused here, so no unit name
    exists to query); pidfile absent + a sibling log → the post-mortem
    tail; else the typed no-destination refusal."""
    if not isinstance(lines, int) or isinstance(lines, bool) or lines <= 0:
        raise LifecycleError(
            f"{LOGS_LINES_DOMAIN} --lines must be a positive integer "
            f"(got {lines!r})"
        )
    bindings = _resolved(bindings)
    record = read_pidfile(bindings)
    if record is not None:
        raw = record.get("log_destination")
        if isinstance(raw, str) and raw:
            if raw == "stderr":
                raise LifecycleError(
                    f"{LOGS_DESTINATION_STDERR} the host was started "
                    "foreground (its bytes went to a terminal this command "
                    "cannot recover) — no journal leg exists on this "
                    "surface (service install is refused here)"
                )
            tokens = tokens_path(bindings)
            if Path(raw).resolve() == tokens.resolve():
                raise LifecycleError(
                    f"{LOGS_DESTINATION_CREDENTIAL} the resolved destination "
                    f"is the tokens file ({tokens}) — the pidfile's "
                    "log_destination is steerable through "
                    "BENCHWEAVE_SDK_LOG_DESTINATION and is refused as a "
                    "tail source; point it back at the <bindings>.log "
                    "sibling"
                )
            return _tail_payload(Path(raw), lines, post_mortem=False)
    log = log_path(bindings)
    if log.is_file():
        return _tail_payload(log, lines, post_mortem=True)
    raise LifecycleError(
        f"{LOGS_NO_DESTINATION} no pidfile names a destination and no "
        f"sibling log exists beside {bindings} — never served, or served "
        "with no log file; nothing to tail"
    )


def _tail_payload(path: Path, lines: int, *, post_mortem: bool) -> dict[str, Any]:
    try:
        tailed = _tail_lines(path, lines)
    except OSError as error:
        raise LifecycleError(
            f"{LOGS_UNREADABLE} cannot tail {path}: {error}"
        ) from error
    payload: dict[str, Any] = {"destination": str(path), "lines": tailed}
    if post_mortem:
        payload["post_mortem"] = True
    return payload
