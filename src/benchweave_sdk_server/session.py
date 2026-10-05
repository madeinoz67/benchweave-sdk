"""The adapter session: loading, lifecycle, and per-operation contexts.

The loader imports the plugin's adapter module with no side effects beyond
the import itself (the project's ``src/`` goes on ``sys.path``; the
descriptor's ``integration.adapter.entry_point`` names the factory), then
validates the descriptor — and the presentation documents, when the project
declares them — before anything binds a port (SW-05). :class:`PluginSession`
then drives one adapter instance through the strict ``Adapter`` lifecycle:
``open`` binds descriptor and services, ``execute`` runs one operation per
fresh context, ``close`` is idempotent-tolerant (REG-1).

Every operation context is bounded by the descriptor's OWN operation policy
(``operations[verb].timeout_ms``): the plugin's declared bound is the bound;
the host adds no uncommissioned envelope (A02's posture). Lifecycle contexts
(open/close — not descriptor verbs) use the strictest declared timeout, a
derived-not-invented bound.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import math
import shutil
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchweave_sdk.interfaces import Adapter, HostServices
from benchweave_sdk.presentation import read_file
from benchweave_sdk.validation import validate_descriptor


class PluginLoadError(ValueError):
    """A plugin project could not be loaded or validated; always prefixed."""


def project_py_digest(plugin: LoadedPlugin) -> str:
    """The loaded project's adapter-code digest: every ``*.py`` file
    under the project's ``src/`` tree (the package AND any top-level
    sibling modules it imports — the loader puts the whole src root on
    ``sys.path``, so a sibling IS loaded adapter code), path-and-bytes,
    sorted. Computed at load, recomputed at reload — the mechanical
    adapter-code/contract-only discrimination Q11's confirmation branch
    rides. A deliberate superset of the exact loaded closure: an edit to
    an unloaded Python file may ask for confirmation unnecessarily, but
    loaded code can never slip PAST the digest."""
    src_root = plugin.project_root / "src"
    hasher = hashlib.sha256()
    for path in sorted(src_root.rglob("*.py")):
        hasher.update(path.relative_to(src_root).as_posix().encode())
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def evict_plugin_modules(package: str, src_root: Path | None = None) -> None:
    """Drop the plugin's modules from the import cache so a reload
    re-executes the CURRENT bytes. ``importlib`` caches by name; without
    eviction a reload would keep handing out the previous adapter object
    forever — the one case where reload silently fails its whole purpose.
    The eviction covers the package, its submodules, AND every cached
    module whose file lives under the project's ``src/`` root (top-level
    siblings the package imports are loaded adapter code too)."""
    prefix = f"{package}."
    for name in [
        module
        for module in list(sys.modules)
        if module == package or module.startswith(prefix)
    ]:
        del sys.modules[name]
    importlib.invalidate_caches()
    if src_root is None:
        return
    # The BYTECODE cache is the second staleness cache: a same-size edit
    # within the same mtime second validates a stale .pyc and the
    # re-import serves the OLD code anyway (observed with the lanes'
    # MARK repro). A reload means "serve the current bytes" — the
    # project's own __pycache__ directories go with the modules.
    for cache_dir in src_root.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)
    root = src_root.resolve()
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            if Path(module_file).resolve().is_relative_to(root):
                del sys.modules[name]
        except OSError:
            continue


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    """A validated plugin project ready to serve.

    ``adapter_factory`` is ``None`` on a DEGRADED load (§4.5): the project's
    documents validated, but its adapter entry point failed to import or
    resolve — ``load_diagnostic`` carries the prefixed reason, device
    operations answer ``not_ready``, and the pages still render.
    """

    project_root: Path
    package: str
    descriptor: dict[str, Any]
    descriptor_sha256: str
    plugin_version: str
    adapter_factory: Any | None = None
    has_presentation: bool = False
    load_diagnostic: str | None = None

    @property
    def device_id(self) -> str:
        """The one device this session serves, named by the descriptor."""
        transport = self.descriptor.get("transport", {})
        return str(transport.get("connection_key") or self.package)

    @property
    def readable_parameters(self) -> list[dict[str, Any]]:
        """Descriptor parameters a readings page may show (ro or rw)."""
        rows = []
        for parameter in self.descriptor.get("parameters", []):
            if parameter.get("access") in ("ro", "rw"):
                rows.append(parameter)
        return rows

    @property
    def package_dir(self) -> Path:
        """The plugin package directory (``src/<package>/``)."""
        return self.project_root / "src" / self.package


#: The session-level per-receive ceiling when the descriptor is silent —
#: the serial session's own fallback (controller ruling 3, the fold: the
#: mock had minted 128; one resolution, both hosts).
SESSION_RECEIVE_CEILING = 4096

#: The backend link's default transfer ceiling — the descriptor bound never
#: exceeds it on either host (the serial link's constructor default is this
#: same constant, imported from here: one definition).
TRANSFER_CEILING = 64 * 1024


def transport_ceiling(settings: dict[str, Any]) -> int:
    """The per-receive ceiling both hosts clamp to: the descriptor's
    declared ``max_frame_bytes``, the session fallback
    :data:`SESSION_RECEIVE_CEILING` when silent, clamped by the backend's
    :data:`TRANSFER_CEILING` (A02: the plugin's declared bound is the
    bound — and a declared bound above the link's own ceiling is still
    bounded by the link)."""
    declared = int(settings.get("max_frame_bytes", 0)) or SESSION_RECEIVE_CEILING
    return min(declared, TRANSFER_CEILING)


#: The vectors.json dialect vocabulary (issue #394's owner ruling (a)):
#: ``stream_exchange`` is the omitted-key default — today's behaviour,
#: byte-for-byte — and ``send_receive`` scripts binary §8.1 SEND/RECEIVE
#: conversations, request-less rows valid (device-initiated frames).
_DIALECTS = ("stream_exchange", "send_receive")

#: The payload encoding vocabulary: ``ascii`` (a row string's ASCII bytes —
#: today's behaviour) and ``hex`` (``bytes.fromhex``).
_ENCODINGS = ("ascii", "hex")


@dataclass(frozen=True, slots=True)
class FrameRow:
    """One decoded vectors.json row of a ``send_receive`` script.

    ``request`` is ``None`` on a response-only row (a device-initiated
    frame, released to the inbound stream in row order); ``name`` is the
    row's declared name or its index, echoed in diagnostics.
    """

    name: str
    request: bytes | None
    response: bytes


@dataclass(frozen=True, slots=True)
class VectorsScript:
    """The validated, decoded vectors.json script (parsed once).

    ``frames`` carries every row decoded to bytes under the file's (or the
    row's) declared encoding; ``mock_exchanges`` (the ``stream_exchange``
    dialect) and ``frame_script`` (``send_receive``) both derive from it.
    """

    dialect: str
    encoding: str
    frames: list[FrameRow]


def _decode_payload(
    text: Any, encoding: str, row_name: str, path: Path, *, coerce: bool
) -> bytes:
    """Decode one row payload under its encoding; typed refusals name the row.

    ``coerce`` is the default dialect's compat mode (controller ruling 2,
    the fold): under ``stream_exchange`` with ASCII payloads, non-string
    payloads coerce through ``str()`` exactly as the merge base's
    ``mock_exchanges`` did — numeric rows (``{"request": 42}``) rehearsed
    at base and must keep rehearsing. The strict string requirement (and
    its typed refusal) applies only where hex/ascii decoding needs a
    string: the ``send_receive`` dialect, or any row that overrides its
    encoding to hex.
    """
    if not isinstance(text, str):
        if coerce:
            # Byte-for-byte the merge base's expression, UnicodeEncodeError
            # included (the connect seam wraps it, as it always did).
            return str(text).encode("ascii")
        raise PluginLoadError(
            f"standalone_vectors_row_shape: row {row_name}: payload is not a string "
            f"in {path}"
        )
    if encoding == "ascii":
        try:
            return text.encode("ascii")
        except UnicodeEncodeError as exc:
            raise PluginLoadError(
                f"standalone_vectors_encoding_invalid: row {row_name}: string is "
                f"not ASCII ({text!r}) in {path}"
            ) from exc
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise PluginLoadError(
            f"standalone_vectors_encoding_invalid: row {row_name}: not a hex byte "
            f"string ({text!r}) in {path}"
        ) from exc


def vectors_script(plugin: LoadedPlugin) -> VectorsScript:
    """Parse and decode the plugin's vectors.json once (issue #394, ruling (a)).

    The declaration is additive: ``transaction_dialect`` (file level,
    default ``stream_exchange`` — today's behaviour) and ``encoding`` (file
    level with a per-row override, default ``ascii``). Every scripting
    problem refuses with a ``standalone_vectors_*:`` prefix naming the row —
    a :class:`PluginLoadError` the connect path maps to a typed ``not_ready``
    (the seam ``standalone_transport_script:`` already rides), never a raw
    ``KeyError``.
    """
    path = plugin.package_dir / "vectors.json"
    vectors = json.loads(read_file(path))
    if not isinstance(vectors, dict):
        raise PluginLoadError(f"standalone_vectors_row_shape: not an object in {path}")
    dialect = vectors.get("transaction_dialect", "stream_exchange")
    if dialect not in _DIALECTS:
        raise PluginLoadError(
            f"standalone_vectors_dialect_unknown: {dialect!r} (expected "
            f'"stream_exchange" or "send_receive") in {path}'
        )
    encoding = vectors.get("encoding", "ascii")
    if encoding not in _ENCODINGS:
        raise PluginLoadError(
            f"standalone_vectors_encoding_unknown: {encoding!r} (expected "
            f'"ascii" or "hex") at file level in {path}'
        )
    rows = vectors.get("exchanges", [])
    if not isinstance(rows, list) or not rows:
        raise PluginLoadError(
            f"standalone_transport_script: no exchanges in {path}"
        )
    coerce = dialect == "stream_exchange" and encoding == "ascii"
    frames: list[FrameRow] = []
    for index, row in enumerate(rows):
        name = str(index)
        if not isinstance(row, dict):
            raise PluginLoadError(
                f"standalone_vectors_row_shape: row {name}: not an object in {path}"
            )
        if "name" in row:
            if not isinstance(row["name"], str) or not row["name"]:
                raise PluginLoadError(
                    f"standalone_vectors_row_shape: row {name}: name is not a "
                    f"non-empty string in {path}"
                )
            name = row["name"]
        row_encoding = row.get("encoding", encoding)
        if row_encoding not in _ENCODINGS:
            raise PluginLoadError(
                f"standalone_vectors_encoding_unknown: {row_encoding!r} (expected "
                f'"ascii" or "hex") for row {name} in {path}'
            )
        coerce_row = coerce and row_encoding == "ascii"
        has_request = "request" in row
        has_response = "response" in row
        if not has_request and not has_response:
            raise PluginLoadError(
                f"standalone_vectors_row_shape: row {name}: carries neither "
                f"request nor response in {path}"
            )
        request: bytes | None = None
        if has_request:
            request = _decode_payload(
                row["request"], row_encoding, name, path, coerce=coerce_row
            )
        if not has_response:
            raise PluginLoadError(
                f"standalone_vectors_row_shape: row {name}: carries no response "
                f"in {path}"
            )
        response = _decode_payload(
            row["response"], row_encoding, name, path, coerce=coerce_row
        )
        if has_request is False and dialect != "send_receive":
            raise PluginLoadError(
                f'standalone_vectors_row_unscriptable: row {name} is '
                f'response-only; response-only rows require '
                f'transaction_dialect: "send_receive" (declared '
                f"{dialect!r}) in {path}"
            )
        frames.append(FrameRow(name=name, request=request, response=response))
    return VectorsScript(dialect=dialect, encoding=encoding, frames=frames)


def mock_exchanges(
    plugin: LoadedPlugin,
) -> list[tuple[dict[str, Any], dict[str, Any] | Exception]]:
    """Build the I1 scripted exchanges from the plugin's own evidence.

    The starter protocol's evidence file (``vectors.json``) carries the
    exact request/response byte pairs, and the descriptor's transport
    settings carry the frame bound — the script is derived from the plugin's
    declared data, not hardcoded host knowledge of any one plugin. The
    transaction shape is the scaffold protocol's own (``stream_exchange``,
    LF termination); a plugin whose adapter speaks a different shape will
    fail the mock's exact-match discipline honestly (R7's accepted bound).

    Since issue #394 the rows parse through :func:`vectors_script`, so a
    response-only row under this (the default) dialect refuses with the
    typed ``standalone_vectors_row_unscriptable:`` instead of today's raw
    ``KeyError: 'request'``.
    """
    script_doc = vectors_script(plugin)
    settings = plugin.descriptor.get("transport", {}).get("settings", {})
    max_bytes = int(settings.get("max_frame_bytes", 0)) or 128
    script: list[tuple[dict[str, Any], dict[str, Any] | Exception]] = []
    for row in script_doc.frames:
        if row.request is None:
            # Reachable only on a direct call over a send_receive-declaring
            # file (the selector routes those to frame_script): this
            # constructor scripts exchanges, and an exchange needs a request.
            raise PluginLoadError(
                f"standalone_vectors_row_unscriptable: row {row.name} is "
                f"response-only and cannot script a stream_exchange in "
                f"{plugin.package_dir / 'vectors.json'}"
            )
        transaction = {
            "kind": "stream_exchange",
            "data": row.request,
            "max_bytes": max_bytes,
            "termination": "lf",
            "exact_bytes": None,
        }
        script.append((transaction, {"data": row.response}))
    if not script:
        raise PluginLoadError(
            f"standalone_transport_script: no exchanges in {plugin.package_dir / 'vectors.json'}"
        )
    return script


def frame_script(plugin: LoadedPlugin) -> list[FrameRow]:
    """The ``send_receive`` frame script: ordered decoded rows (issue #394).

    Request-bearing rows script one command frame and its response bytes;
    response-only rows script device-initiated frames released in row
    order. Parsed through :func:`vectors_script`, so the refusal family is
    the same typed ``standalone_vectors_*:`` set.
    """
    return vectors_script(plugin).frames


def _cycle_plan(rows: list[FrameRow]) -> tuple[int, list[FrameRow], int]:
    """The minimal-period cycle plan for a ``send_receive`` script:
    ``(establishment, cycle unit, rotate)``.

    The cycle unit is the SHORTEST suffix-unit that, repeated from the
    establishment boundary, regenerates the captured tail exactly, with at
    least TWO full units of evidence and at least one request-bearing row
    in the unit (a cycle that can never accept a command is not a poll
    cycle). Ties on unit length resolve to the earliest boundary. A capture
    that ended mid-unit continues at the captured phase: the restored unit
    is rotated by ``len(tail) % len(unit)``. No derivable unit — a
    truncated capture, or a script whose responses VARY across occurrences
    of the same request (any measured reading: the polled value differs
    each cycle) — falls back to ``LoopingMockHost``'s own rule: an
    establishment head of one, the whole tail the cycle, replayed in
    captured order (the guide says capture at least two full poll cycles;
    a truncated capture is ambiguous evidence). The establishment may be
    empty (boundary 0) when the whole script is the repeating unit —
    ``LoopingMockHost``'s establishment=0 precedent.
    """
    n = len(rows)
    # Conversation identity, precomputed once: the (request, response) byte
    # pairs — never the diagnostic row names ("poll-1" and "poll-2" are the
    # same cycle step).
    shapes = [(row.request, row.response) for row in rows]
    # One early-exit pass per candidate period (the fold-refute lane's Fix 2:
    # the old scan materialised the full tail for EVERY (p, e) candidate —
    # cubic, ~150 s at n=2000 on the synchronous connect path). The suffix
    # from e is p-periodic exactly when no i >= e+p violates
    # shapes[i] == shapes[i-p]; the LAST violating i bounds the earliest
    # valid boundary, so each period costs O(n) and the whole scan O(n^2)
    # with no per-candidate allocation. Tie rules preserved: periods ascend
    # (minimal wins), boundaries ascend from the earliest valid e.
    for p in range(1, n // 2 + 1):
        last_violation = -1
        for i in range(p, n):
            if shapes[i] != shapes[i - p]:
                last_violation = i
        earliest = max(0, last_violation - p + 1)
        for e in range(earliest, n - 2 * p + 1):
            unit = rows[e : e + p]
            if not any(row.request is not None for row in unit):
                continue
            return e, list(unit), (n - e) % p
    cycle = rows[1:] if len(rows) > 1 else list(rows)
    return 1, cycle, 0


def mock_transport_factory(
    plugin: LoadedPlugin, *, capture_root: Any = None
) -> Callable[[], HostServices]:
    """The dialect selector (issue #394): which mock host serves the plugin.

    ``stream_exchange`` (the omitted-key default) builds the
    :class:`LoopingMockHost` over :func:`mock_exchanges` — today's host,
    byte-for-byte. ``send_receive`` builds the :class:`ByteStreamMockHost`
    over :func:`frame_script` with the descriptor's own frame bound. The
    factory is returned LATE-BOUND on ``plugin`` exactly as
    :func:`mock_plugin_session` is: call it at connect time against the
    session's CURRENT plugin so a reload's reconnect speaks the reloaded
    plugin's own script (the M1-fold closure shape).
    """
    from .transport import ByteStreamMockHost, LoopingMockHost

    dialect = vectors_script(plugin).dialect
    if dialect == "send_receive":
        settings = plugin.descriptor.get("transport", {}).get("settings", {})
        max_frame = transport_ceiling(settings)
        rows = frame_script(plugin)
        establishment, cycle, rotate = _cycle_plan(rows)
        return lambda: ByteStreamMockHost(
            rows,
            establishment=establishment,
            cycle=cycle,
            cycle_rotate=rotate,
            max_frame_bytes=max_frame,
            capture_root=capture_root,
        )
    return lambda: LoopingMockHost(mock_exchanges(plugin))


def _evict_foreign_package(package: str, src: Path) -> None:
    """Drop cached modules of ``package`` whose files live OUTSIDE this
    project's src root, so a fresh load imports THIS project's bytes (the
    import cache is keyed by name, not by path)."""
    root = src.resolve()
    prefix = f"{package}."
    for name in list(sys.modules):
        if name != package and not name.startswith(prefix):
            continue
        module_file = getattr(sys.modules.get(name), "__file__", None)
        if not module_file:
            continue
        try:
            if not Path(module_file).resolve().is_relative_to(root):
                del sys.modules[name]
        except OSError:
            continue


def load_plugin_project(project_root: Path) -> LoadedPlugin:
    """Load and validate one plugin project; refuse before any port binds.

    Raises
    ------
    PluginLoadError
        With a ``standalone_plugin_*:`` prefix (SW-05) carrying the SDK's
        own diagnostic text for validation failures.
    """
    root = project_root.expanduser().resolve()
    src = root / "src"
    if not src.is_dir():
        raise PluginLoadError(f"standalone_plugin_project: no src/ under {root}")
    candidates = sorted(p.parent for p in src.glob("*/descriptor.json"))
    if len(candidates) != 1:
        raise PluginLoadError(
            f"standalone_plugin_project: expected exactly one src/*/descriptor.json "
            f"under {root}, found {len(candidates)}"
        )
    package_dir = candidates[0]
    package = package_dir.name
    descriptor_path = package_dir / "descriptor.json"
    try:
        raw = read_file(descriptor_path)
    except (OSError, ValueError) as exc:
        raise PluginLoadError(f"standalone_plugin_invalid: {descriptor_path}: {exc}") from exc
    try:
        descriptor = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PluginLoadError(f"standalone_plugin_invalid: {descriptor_path}: {exc}") from exc
    try:
        validate_descriptor(descriptor)
    except (ValueError, KeyError, TypeError) as exc:
        raise PluginLoadError(f"standalone_plugin_invalid: {exc}") from exc

    entry_point = str(
        descriptor.get("integration", {}).get("adapter", {}).get("entry_point", "")
    )
    module_name, _, factory_name = entry_point.partition(":")
    adapter: Any | None = None
    diagnostic: str | None = None
    if not module_name.startswith(f"{package}.") or not factory_name:
        # Adapter-failure class (§4.5): the entry point STRING is part of
        # the adapter surface, not the documents — a malformed one degrades
        # (layout renders, device ops not_ready) instead of refusing.
        diagnostic = (
            f"standalone_plugin_entry_point: {entry_point} does not name a factory "
            f"inside the {package} package"
        )
    else:
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        # A same-named package cached from ANOTHER project's root would win
        # the import by name and serve ITS bytes (invisible while every
        # test project had identical content; a broken or edited sibling
        # makes it load wrong code on a FRESH load). The reload path
        # pre-evicts; a fresh load defends itself the same way.
        _evict_foreign_package(package, src)
        try:
            module = importlib.import_module(module_name)
            adapter = getattr(module, factory_name)
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - plugin import code
            # ANY exception raised while executing the plugin's adapter
            # module at import time is an adapter import failure — the
            # tuple form let a module-level NameError (the lanes' arm)
            # escape as a raw traceback instead of the degraded load.
            # SystemExit is BaseException, NOT Exception: it stays listed
            # explicitly because a plugin calling sys.exit() at import
            # must degrade the load, not kill the host (refute fold 2).
            # Refute fold 2: SyntaxError (the most common authoring failure —
            # it previously escaped as a raw traceback with serve exit 1)
            # and SystemExit (a plugin calling sys.exit() at import
            # previously swallowed serve into the plugin's own exit code)
            # are import-time adapter failures — they degrade like the rest.
            diagnostic = f"standalone_plugin_import: {entry_point}: {exc}"

    presentation_path = package_dir / "presentation.json"
    has_presentation = presentation_path.is_file()
    if has_presentation:
        from benchweave_sdk.presentation import load_validated_preview_inputs

        from .presentation import SUPPORTED_FEATURES, SUPPORTED_PANELS

        try:
            load_validated_preview_inputs(
                presentation_path,
                descriptor_path,
                package_dir,
                package_dir / "binding-catalogue.json",
                firmware=None,
                features=SUPPORTED_FEATURES,
                panels=SUPPORTED_PANELS,
            )
        except (ValueError, OSError) as exc:
            raise PluginLoadError(f"standalone_plugin_invalid: {exc}") from exc

    plugin_version = str(
        descriptor.get("integration", {}).get("adapter", {}).get("version", "unknown")
    )
    return LoadedPlugin(
        project_root=root,
        package=package,
        descriptor=descriptor,
        descriptor_sha256=hashlib.sha256(raw).hexdigest(),
        plugin_version=plugin_version,
        adapter_factory=adapter,
        has_presentation=has_presentation,
        load_diagnostic=diagnostic,
    )


def mock_plugin_session(
    plugin: LoadedPlugin, *, capture_root: Any = None
) -> PluginSession:
    """A session whose mock factory derives its script from the CURRENT
    plugin at connect time — a reload swaps the loaded plugin and the next
    connection speaks the new plugin's own vectors (a closure over the
    ORIGINAL plugin would keep serving the previous version's script; the
    late-bound ``session.plugin`` read cannot go stale).

    Since issue #394 the factory is the dialect selector
    (:func:`mock_transport_factory`): the plugin's own vectors.json
    declaration picks the exchange host or the byte-stream host.
    ``capture_root`` is the host's capture configuration, threaded the same
    way ``serial_plugin_session`` threads it (the byte-stream host serves
    the capture lifecycle over it).
    """
    session: PluginSession = PluginSession(
        plugin,
        lambda: mock_transport_factory(session.plugin, capture_root=capture_root)(),
    )
    return session


class HostOperationContext:
    """A live ``OperationContext``: real clock, descriptor-declared deadline.

    ``deadline_monotonic`` is ``time.monotonic() + timeout_ms / 1000`` where
    ``timeout_ms`` comes from the descriptor's own operation policy for the
    verb being executed (SW-13): the host mints no envelope of its own.
    """

    def __init__(self, operation_id: str, *, timeout_ms: int) -> None:
        if not operation_id or not math.isfinite(float(timeout_ms)) or timeout_ms <= 0:
            raise ValueError("A context needs an identity and a positive finite timeout")
        self.operation_id = operation_id
        self.dataset_id: str | None = None
        self.deadline_monotonic = time.monotonic() + timeout_ms / 1000
        self.dispatched = False
        self._cancelled = False

    def is_cancelled(self) -> bool:
        """Report whether :meth:`cancel` has been called."""
        return self._cancelled

    def cancel(self) -> None:
        """Cancel cooperatively; subsequent transfers must fail, not transmit."""
        self._cancelled = True

    async def mark_dispatch_started(self) -> None:
        """Record the dispatch marker immediately before the first transmit."""
        self.dispatched = True


class PluginSession:
    """One adapter session over a per-connection transport (SW-04's shape).

    The services object is minted FRESH by ``services_factory`` on every
    connect: a disconnect closes that transport for good (the mock's
    ``close_transport`` never reopens), and a reconnect must start a new
    scripted conversation from its establishment head — reusing one
    process-lifetime host leaves a fresh adapter talking to a dead
    transport mid-cycle (the M1 fold). Connecting then establishes the
    device's identity once (the gateway's own admission shape: identity is
    an establishment fact, not a pollable); ``device_get`` serves the
    established identity afterwards. Over the deterministic scripted
    transport the cached identity is exact; a real transport (I3)
    re-establishes on connect the same way.
    """

    def __init__(
        self, plugin: LoadedPlugin, services_factory: Callable[[], HostServices]
    ) -> None:
        self._plugin = plugin
        self._services_factory = services_factory
        self._adapter: Adapter | None = None
        self.identity: dict[str, Any] | None = None
        self.connected = False
        # The services object the connected adapter holds (I3b's capture
        # lifecycle): minted per connection, retained so the host can drive
        # the capture members (configure/progress/finalise/abort) on the
        # SAME object the adapter appends through. None while disconnected.
        self.services: HostServices | None = None

    @property
    def plugin(self) -> LoadedPlugin:
        return self._plugin

    @property
    def device_id(self) -> str:
        return self._plugin.device_id

    def _lifecycle_timeout_ms(self) -> int:
        """The strictest declared operation timeout (open/close are not verbs)."""
        policies = self._plugin.descriptor.get("operations", {})
        timeouts = [int(row.get("timeout_ms", 0)) for row in policies.values()]
        return max(timeouts) if timeouts else 1000

    @property
    def lifecycle_timeout_ms(self) -> int:
        """The strictest declared timeout, for host-minted lifecycle contexts
        (the capture terminal paths finalise/abort under one)."""
        return self._lifecycle_timeout_ms()

    def _context(self, operation_id: str, timeout_ms: int) -> HostOperationContext:
        return HostOperationContext(operation_id, timeout_ms=timeout_ms)

    def verb_timeout_ms(self, verb: str) -> int:
        """The descriptor's declared timeout for ``verb`` (A02: its bound)."""
        policy = self._plugin.descriptor.get("operations", {}).get(verb, {})
        timeout_ms = int(policy.get("timeout_ms", 0))
        if timeout_ms <= 0:
            raise KeyError(f"standalone_verb_unbounded: {verb}")
        return timeout_ms

    async def connect(self) -> None:
        """Open the adapter session and establish the device's identity.

        ``open`` is contractually device-I/O free; the establishment
        ``identify`` that follows is the session's first exchange. A failed
        establishment fails the connect (the adapter closes again) — an
        adapter that cannot say who it is has not connected.
        """
        if self.connected or self._adapter is not None:
            raise RuntimeError("standalone_session_connected")
        if self._plugin.adapter_factory is None:
            # The degraded load (§4.5): documents validated, the adapter
            # did not — the diagnostic IS the refusal's reason.
            raise RuntimeError(
                self._plugin.load_diagnostic or "standalone_plugin_not_ready"
            )
        import contextlib

        try:
            # Refute fold 2 (connect-time classes): a factory that raises
            # when called, a factory returning a non-Adapter, and an
            # open() that raises all previously surfaced as bare 500s —
            # every connect-time failure is a typed not_ready carrying a
            # prefixed diagnostic, never an unhandled exception.
            adapter = self._plugin.adapter_factory()
            if not callable(getattr(adapter, "open", None)) or not callable(
                getattr(adapter, "execute", None)
            ):
                raise TypeError(
                    f"adapter factory returned {type(adapter).__name__!r}, "
                    "which is not an Adapter (no open/execute)"
                )
            context = self._context(
                f"open-{uuid.uuid4().hex[:8]}", self._lifecycle_timeout_ms()
            )
            services = self._services_factory()
            await adapter.open(self._plugin.descriptor, services, context)
        except RuntimeError:
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                await adapter.close(context)
            raise RuntimeError(
                f"standalone_plugin_connect: {type(exc).__name__}: {exc}"
            ) from exc
        self._adapter = adapter
        self.connected = True
        self.services = services
        try:
            if "identify" in self._plugin.descriptor.get("capabilities", []):
                envelope = await self.execute("identify", {})
                if envelope.get("status") != "ok":
                    raise RuntimeError(
                        "standalone_connect_failed: "
                        f"{(envelope.get('error') or {}).get('code', 'unknown')}"
                    )
                data = envelope.get("data")
                if isinstance(data, dict):
                    self.identity = dict(data)
        except BaseException:
            await self.close()
            raise

    async def execute(self, verb: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one operation envelope through the open adapter."""
        if self._adapter is None or not self.connected:
            raise RuntimeError("standalone_session_not_open")
        timeout_ms = self.verb_timeout_ms(verb)
        operation_id = f"op-{uuid.uuid4().hex[:8]}"
        context = self._context(operation_id, timeout_ms)
        request = {"operation_id": operation_id, "verb": verb, "arguments": arguments}
        return await self._adapter.execute(request, context)

    def begin_verb(
        self, verb: str, arguments: dict[str, Any]
    ) -> tuple[asyncio.Task[dict[str, Any]], HostOperationContext]:
        """Dispatch one operation envelope WITHOUT awaiting it: the host's
        capture lifecycle holds the task and the context so its watchdog can
        cancel the context at the bound while the adapter runs on. The
        timeout policy is the verb's own declared bound (A02), exactly as
        :meth:`execute` applies it.
        """
        if self._adapter is None or not self.connected:
            raise RuntimeError("standalone_session_not_open")
        timeout_ms = self.verb_timeout_ms(verb)
        operation_id = f"op-{uuid.uuid4().hex[:8]}"
        context = self._context(operation_id, timeout_ms)
        request = {"operation_id": operation_id, "verb": verb, "arguments": arguments}
        task: asyncio.Task[dict[str, Any]] = asyncio.create_task(
            self._adapter.execute(request, context)
        )
        return task, context

    async def close(self) -> None:
        """Close the session; tolerates repeated calls (Adapter.close rule)."""
        adapter, self._adapter = self._adapter, None
        self.connected = False
        self.services = None
        if adapter is not None:
            context = self._context(
                f"close-{uuid.uuid4().hex[:8]}", self._lifecycle_timeout_ms()
            )
            await adapter.close(context)

    async def reload_plugin(self, plugin: LoadedPlugin) -> None:
        """Swap the loaded plugin: run the adapter's quiet/disconnect path
        on the session it was serving, then bind the new plugin with a
        clean slate (no identity, not connected). The caller reconnects if
        the session was open; a load that failed never reaches here, so
        the previous version is structurally the one that stays loaded
        until this method swaps it atomically."""
        await self.close()
        self.identity = None
        self._plugin = plugin
