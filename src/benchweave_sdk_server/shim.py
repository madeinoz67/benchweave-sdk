"""The stdio MCP shim (issue #440, Q5 option 2): proxy to the verified
running host, the disclosed in-process fallback, or a typed refusal.

One session owner per device: the shim holds no state and opens no
store. Discovery is pure-read over the supervision family (the landed
lifecycle twins): ``ours`` + usable tokens proxies; ``absent``/``dead``
falls back (fork guard first); ``unknown``/``not-ours`` — or a live host
whose tokens are unusable — refuses typed. In proxy mode the shim opens
no capture root at all; before any fallback engages, the capture root's
``library.lock`` is read (never stolen) and a live holder refuses. The
shim writes no pidfile, no journal row, no tokens file, no bindings
byte, and no capture-root byte.

The proxy is fastmcp's own ``ProxyProvider`` composed over a streamable
HTTP client factory (SH0 proved the composition forwards the host's
pinned tool bytes canonically on fastmcp 4.0.11); frame-level
stdio↔HTTP plumbing is not used at any stage.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import lifecycle

if TYPE_CHECKING:
    from fastmcp import Client, FastMCP

    from .seam import StandaloneSeam

#: The wire-visible mode markers (§2.5; pinned by SH9, mutually
#: exclusive). The initialize-level instructions are the only layer the
#: shim owns in both modes — ``host_info`` cannot carry a marker because
#: the host's bytes are the parity subject (identical whether the agent
#: arrives direct or through the shim).
PROXY_MARKER_TEMPLATE = (
    "stdio shim: proxying to the running host at {url} (pid {pid}); "
    "the browser session and this agent share one host."
)

FALLBACK_MARKER = (
    "in-process fallback host: no other surface can attach; no browser "
    "session shares this process; captures taken in this session are "
    "ephemeral — discarded at exit."
)

#: The fallback's startup disclosure (stderr, never stdout — stdout is
#: the protocol channel). Names the verdict, per SH4, and the fold-R5
#: ephemeral-capture isolation.
FALLBACK_STDERR_LINE = (
    "benchweave-sdk-server: no running host beside {bindings} "
    "(verdict: {verdict}); serving the in-process fallback — no browser "
    "can attach to this session, and captures in this session are "
    "ephemeral (discarded at exit)"
)

#: The §2.6 authoring degrade (proxy mode): a degraded session beats no
#: session, loudly (D4 keeps the typed-refusal alternative deferred).
AUTHORING_DEGRADE_LINE = (
    "benchweave-sdk-server: authoring requested; the running host does "
    "not serve authoring tools — restart it with --authoring"
)

#: Fold R3: the §2.6 principle applied to the probe itself — a probe
#: that cannot run discloses and serves (never a raw traceback out of
#: an agent session).
AUTHORING_PROBE_FAILED_LINE = (
    "benchweave-sdk-server: the authoring probe against the running "
    "host failed ({detail}); serving the proxy — the host's own tool "
    "list decides authoring presence"
)

#: Fold R11: the disclosed timeout posture. Declared, not invented: no
#: commissioned bound exists on this surface, so the shim waits as long
#: as the in-process host would — and says so, loudly, once.
PROXY_TIMEOUT_DISCLOSURE = (
    "benchweave-sdk-server: proxying with no call timeout — a hung host "
    "holds this session (the in-process host has the same posture; no "
    "commissioned bound exists)"
)

#: The three shim refusal prefixes — the STD-4 amendment's additions.
SUPERVISION_UNKNOWN_PREFIX = "standalone_supervision_unknown:"
HOST_UNPROXYABLE_PREFIX = "standalone_host_unproxyable:"
CAPTURE_ROOT_HELD_PREFIX = "standalone_capture_root_held:"


@dataclass(frozen=True)
class ProxyTarget:
    """A verified, authenticate-able host: proxy."""

    url: str
    bearer: str
    pid: int


@dataclass(frozen=True)
class NoHost:
    """No host holds the family: fallback, disclosed."""

    reason: str


@dataclass(frozen=True)
class Refuse:
    """A typed refusal; the message names its resolving action."""

    prefix: str
    detail: str
    action: str


def _plausible_pid(value: object) -> bool:
    """The OS-mintable range (fold R4): a pid outside it is never probed
    with an os.kill — the conservative refusal covers it instead."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 < value <= 2**31 - 1
    )


def _supervision_refuse(detail: str, bindings: Path) -> Refuse:
    """The unknown-class refusal with the TRUTHFUL action sentence
    (fold R6, probe-proven): no lifecycle verb clears this verdict —
    ``status`` observes it and ``stop`` refuses on it — so the sentence
    names the stale pidfile's path and the removal that actually
    resolves it. The no-verb-clears-it lifecycle gap is a disclosed
    deferral (the addendum's R12 rows)."""
    return Refuse(
        prefix=SUPERVISION_UNKNOWN_PREFIX,
        detail=detail,
        action=(
            "no lifecycle verb clears this verdict (status observes it; "
            "stop refuses on it) — remove the stale pidfile at "
            f"{lifecycle.pid_path(bindings)} by hand once you are sure "
            "the pid is not a live host"
        ),
    )


def discover(bindings: Path) -> ProxyTarget | NoHost | Refuse:
    """The §2.2 lattice over the supervision family, pure-read.

    ``absent``/``dead`` → fallback; ``unknown``/``not-ours`` → typed
    refusal (the shim neither proxies nor forks beside a process it
    cannot verify); ``ours`` → the tokens file decides: usable
    (parses, bearer+url present, ``tokens.pid == pidfile.pid``)
    proxies — unusable refuses, because a live host IS the family's
    owner and a fallback beside it is the fork's shape. The S7
    tokens-before-pidfile ordering makes tokens-absent-while-ours a
    real anomaly worth refusing on, not a race to retry.

    The fold wave's hardenings: a pidfile that EXISTS but cannot be
    read or parsed is the collapse refusal (never a fallback — R1);
    tokens WITHOUT a pidfile is the mid-boot window refusal (S7's
    ordering means a host may be coming up — R2); a pid outside the
    OS-mintable range refuses before any os.kill probe (R4).
    """
    record = lifecycle.read_pidfile(bindings)
    if record is None:
        if lifecycle.pid_path(bindings).exists():
            # Fold R1: present but unreadable (cross-user 0600) or
            # unparseable — verify_identity would read this as "absent"
            # and FALL BACK beside a family it cannot see. Refuse.
            return _supervision_refuse(
                "the pidfile exists beside "
                f"{bindings} but could not be read or parsed by this "
                "user; the family's owner cannot be verified",
                bindings,
            )
        if lifecycle.tokens_path(bindings).is_file():
            # Fold R2: the mid-boot window — the tokens file lands
            # BEFORE the pidfile (S7), so this family may have a host
            # coming up; falling back beside it is the fork's shape.
            return Refuse(
                prefix=SUPERVISION_UNKNOWN_PREFIX,
                detail=(
                    "the tokens file exists without a pidfile beside "
                    f"{bindings} — the mid-boot window (the tokens file "
                    "lands before the pidfile), so a host may be coming "
                    "up; the shim neither proxies nor forks beside it"
                ),
                action=(
                    "retry shortly; once sure no host is coming, remove "
                    f"the stale tokens file at {lifecycle.tokens_path(bindings)}"
                ),
            )
        return NoHost(reason="absent")
    pid = record.get("pid")
    if not _plausible_pid(pid):
        # Fold R4: never hand an implausible pid to an os.kill probe.
        return _supervision_refuse(
            f"the pidfile's pid {pid!r} is outside the range an OS "
            f"mints; the family beside {bindings} cannot be verified",
            bindings,
        )
    assert isinstance(pid, int)  # _plausible_pid passed; narrows for mypy
    verdict = lifecycle.verify_identity(bindings)
    if verdict in ("absent", "dead"):
        return NoHost(reason=verdict)
    if verdict in ("unknown", "not-ours"):
        return _supervision_refuse(
            "the pidfile's process could not be verified "
            f"(verdict {verdict!r} beside {bindings}); the shim "
            "neither proxies nor forks beside a process it cannot "
            "verify",
            bindings,
        )
    target = _read_tokens(bindings, int(pid))
    if target is None:
        return Refuse(
            prefix=HOST_UNPROXYABLE_PREFIX,
            detail=(
                f"a live host (pid {pid}) owns the family at {bindings} "
                "but its delivery file could not be used (absent, "
                "unreadable by this user, stale pid, or payload-"
                "incomplete)"
            ),
            action=(
                "stop/restart the host under the reading user: "
                "benchweave-sdk-server stop then start"
            ),
        )
    return target


def _read_tokens(bindings: Path, pid: int) -> ProxyTarget | None:
    """The tokens payload as a proxy target; ``None`` when unusable.

    Usable iff: the file parses, ``bearer_token`` and ``url`` are
    present strings, and ``tokens.pid == pidfile.pid`` — both family
    sources must agree (the combined predicate is a conjunction; there
    is no precedence between them).
    """
    try:
        raw = lifecycle.tokens_path(bindings).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    bearer = payload.get("bearer_token")
    url = payload.get("url")
    tokens_pid = payload.get("pid")
    if not (
        isinstance(bearer, str)
        and bearer
        and isinstance(url, str)
        and url
        and isinstance(tokens_pid, int)
        and not isinstance(tokens_pid, bool)
        and tokens_pid == pid
    ):
        return None
    return ProxyTarget(url=url, bearer=bearer, pid=int(tokens_pid))


def fork_guard(root: Path | None = None) -> Refuse | None:
    """The §2.3 capture-root fork guard: read, never write.

    Resolves the capture root the fallback would use (the same
    resolution the seam applies, without opening anything) and reads
    its ``library.lock`` through :func:`library.read_lock`. A live or
    unprovable holder refuses typed — the two host classes the shim
    cannot proxy to (a foreground serve; a started host under another
    user) are exactly the classes that DO hold the root once they
    capture. A ValueError from the capture-root resolution propagates:
    the caller maps it to the surface's own typed refusal.
    """
    from benchweave_sdk.capture import capture_root

    from .library import read_lock

    resolved = capture_root(root)
    read = read_lock(resolved)
    if read is not None and read.live:
        holder = f"pid {read.pid}" if read.pid is not None else "an unprovable pid"
        return Refuse(
            prefix=CAPTURE_ROOT_HELD_PREFIX,
            detail=(
                f"the capture root {resolved} is held by a live library "
                f"({holder}); falling back would be the two-writers "
                "hazard the lock already refuses"
            ),
            action=(
                "run a supervised host with benchweave-sdk-server start, "
                "or stop the foreground host holding the root"
            ),
        )
    return None


def proxy_instructions(target: ProxyTarget) -> str:
    """The proxy mode's initialize-level marker (names the host)."""
    return PROXY_MARKER_TEMPLATE.format(url=target.url, pid=target.pid)


def build_shim_proxy(target: ProxyTarget) -> FastMCP:
    """The §2.4 proxy server: the host's own MCP machinery, forwarded.

    serverInfo keeps the distribution name (#309 F1: the name is
    wire-visible and names the distribution it rides). The tool set,
    schemas, descriptions and call results are the HOST's — the shim
    adds no tool, subtracts none, and pins nothing itself. One client
    connection for the shim's lifetime (the factory reuses it);
    caching is off — the shim holds no state.
    """
    from fastmcp import Client, FastMCP
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.server.providers.proxy import ProxyProvider

    client: Client[Any] | None = None

    def factory() -> Client[Any]:
        nonlocal client
        if client is None:
            client = Client(
                StreamableHttpTransport(
                    f"{target.url}/mcp",
                    headers={"Authorization": f"Bearer {target.bearer}"},
                )
            )
        return client

    server = FastMCP(
        "benchweave-sdk-server",
        instructions=proxy_instructions(target),
    )
    server.add_provider(ProxyProvider(factory, cache_ttl=0))
    return server


def host_serves_authoring(target: ProxyTarget) -> bool:
    """One tools/list round-trip over the target: does the running host
    serve the authoring tools (the §2.6 degrade probe)?

    Fold R3: the probe is best-effort — a host whose URL is dead (or a
    transport that fails for any reason) raises out of the client; the
    CALLER (the mcp command) catches and discloses, treating the probe
    as not-authoring. The §2.6 principle applies to the probe itself:
    a degraded session beats none, loudly."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async def _probe() -> bool:
        async with Client(
            StreamableHttpTransport(
                f"{target.url}/mcp",
                headers={"Authorization": f"Bearer {target.bearer}"},
            )
        ) as client:
            tools = await client.list_tools()
        return "plugin_new" in {str(tool.name) for tool in tools}

    return bool(asyncio.run(_probe()))


def build_fallback_server(seam: StandaloneSeam, *, authoring: bool) -> FastMCP:
    """Today's in-process body, verbatim, plus the mode marker.

    The host's instruction text is kept (the seam's own words) and the
    fallback marker is APPENDED — never a host-side byte change: the
    marker lives only in the shim's initialize instructions.
    """
    from .mcp import build_mcp

    server = build_mcp(seam, authoring=authoring)
    server.instructions = f"{server.instructions} {FALLBACK_MARKER}"
    return server
