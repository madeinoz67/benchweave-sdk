"""The #568 live FTDI provider transport: a third standalone transport.

Where the serial backend serves the GENERIC section 8.1 stream kinds over a
real port, and the replay transport serves a RECORDED journal of those kinds
plus the pinned contract's provider kinds (#564), this transport opens an
FTDI-class USB device and serves BOTH families against the real hardware
API: the pinned contract's provider kinds through the device's control
calls, and the section 8.1 stream kinds through the same device's data
pipe. The plugin-side adapter work stays on #562; recorded replay stays on
#564 and this module never touches it.

Module contract (pinned by ``tests/server/test_ftdi.py``):

- **Only the driver is doubled — and the double SHIPS here (§3, the
  2026-10-28 ruling).** :class:`ScriptedFtdiDriver` is a committed,
  documented :class:`FtdiDriver` double, not a test-internal fake: its
  script is the #564 journal's row shape, it enforces the exact-match
  discipline (an unexpected call or an exhausted script is a
  ``ConformanceError`` naming the call), and the rehearsal it serves runs
  the PRODUCTION path end to end — ``ftdi_plugin_session(plugin, url,
  driver_factory=lambda url: ScriptedFtdiDriver(rows))`` mints real
  :class:`FtdiCaptureServices` over it, so grammar validation, the feature
  gate, the busy guard, dispatch marker, table dispatch, result
  validation, the inherited :class:`~benchweave_sdk_server.serial.SerialLink`
  receive ladder and the capture sidecar are all the shipped code. The
  acceptance double's script is the SYNTHETIC bring-up fixture (a fixture
  authored to the #564 journal's row shape — no recording exists in-tree,
  and the fixture claims none): the rehearsal and the fixture consume one
  document and cannot drift (the parity rule; the live-device acceptance
  leg runs on a real bench, CI cannot hold the device).
- **The served set is bound twice.** The feature gate binds identity to
  the BANKED BYTES (the pinned contract must be digest-equal to this
  SDK's banked instance for the feature line it claims — a feature-id
  prefix alone launders semantics, the anti-laundering bind); the grammar
  probe binds surface (every op in the dispatch table must validate
  against the pinned grammar at serve construction and at every reconnect
  — a pinned lookalike whose grammar cannot express the seven ops
  refuses, never serves selectively).
- **One bounded attempt, never a retry (A06).** A driver exception maps to
  :class:`ConnectionError` naming the class and the driver call happens
  exactly once; a faulted driver stays faulted (reconnect required). An
  absent device, a busy device, a permission refusal and a missing libusb
  backend are all one refusal — ``live_provider_device_unavailable:``
  naming the exception class, raised at connect, seam-mapped to
  ``not_ready``.
- **The capture sidecar names the transport and the contract.**
  ``configure_capture`` composes ``config.transport = "ftdi"`` and
  ``config.provider = {feature_id, sha256}`` (the pinned contract's
  digest) — the durable evidence names what served, and a capture made
  over the live provider transport names the contract revision that
  governed its wire grammar.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import re
import threading
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from benchweave_sdk.testing import ConformanceError

from .replay import (
    BULK_INLINE_LIMIT,
    GrammarEntry,
    _first_schema_error,
    _grammar,
)
from .serial import SerialCaptureServices, SerialLink, _identify_timeout_ms
from .session import LoadedPlugin, PluginSession, transport_ceiling

_LOGGER = logging.getLogger(__name__)


class FtdiDriver(Protocol):
    """The ten hardware calls the seven contract ops plus the data pipe
    need, nothing else — :mod:`benchweave_sdk_server.serial`'s injectable
    ``Transport`` posture one level up: tests never need a device.

    The method names are the EXECUTOR's protocol, spelled for the contract's
    ops; :func:`open_ftdi` owns the whole mapping onto pyftdi's own call
    names (``reset``, the ``timeouts`` property, ``set_latency_timer``,
    ``set_baudrate``, ``purge_rx_buffer``/``purge_tx_buffer``), so a pyftdi
    API change is a one-function change.
    """

    def reset_device(self) -> None: ...

    def set_timeouts(self, read_ms: int, write_ms: int) -> None: ...

    def set_latency(self, ms: int) -> None: ...

    def set_baud(self, baud: int) -> None: ...

    def purge(self, queue: str) -> None: ...
    # ``queue`` is ``"tx"`` or ``"rx"`` — the contract's declared enum.

    def set_bitmode(self, mask: int, mode: int) -> None: ...

    def read_pins(self) -> int: ...

    def write_data(self, data: bytes) -> int: ...

    def read_data(self, size: int) -> bytes: ...

    def close(self) -> None: ...


#: The op dispatch table: each contract op to its parameter names, in the
#: order the driver call receives them. The table is the executor's declared
#: vocabulary, the load-time grammar probe's input, and the runtime
#: dispatch's authority — an op outside it refuses
#: ``live_provider_op_unknown:`` (the version-skew belt: a newer pinned
#: contract may carry an op this executor predates).
_OPS: dict[str, tuple[str, ...]] = {
    "reset_device": (),
    "set_timeouts": ("read_ms", "write_ms"),
    "set_latency": ("ms",),
    "set_baud": ("baud",),
    "purge": ("queue",),
    "set_bitmode": ("mask", "mode"),
    "read_pins": (),
}

#: One minimal conforming payload per op, authored beside the table: the
#: grammar probe validates each against the pinned contract's request
#: schema at serve construction and at every reconnect, so the executor's
#: declared vocabulary and the admitted grammar are proven to agree before
#: any device opens (the surface half of the served-set bind).
_PROBE_PAYLOADS: dict[str, dict[str, Any]] = {
    "reset_device": {"op": "reset_device"},
    "set_timeouts": {"op": "set_timeouts", "read_ms": 50, "write_ms": 500},
    "set_latency": {"op": "set_latency", "ms": 16},
    "set_baud": {"op": "set_baud", "baud": 115200},
    "purge": {"op": "purge", "queue": "rx"},
    "set_bitmode": {"op": "set_bitmode", "mask": 0xFF, "mode": 0x40},
    "read_pins": {"op": "read_pins"},
}

#: The feature family this transport serves: the banked FTDI common control
#: contract's feature ids all carry this prefix (identity half of the
#: served-set bind — the executor's approval basis is the banked contract,
#: and serving an unreviewed lookalike feature would launder that approval
#: onto foreign semantics).
_FEATURE_PREFIX = "otdp.transport.ftdi-control/"

#: A semantic-version tail for the feature id (three numeric components —
#: the contract family's own spelling). The tail names the banked
#: instance to bind against: a revision is served only when THIS SDK
#: banks that line's bytes (the anti-laundering bind, the delta fold's
#: correction — a tail alone never admits a lookalike).
_SEMVER = re.compile(r"\d+\.\d+\.\d+\Z")

#: The idle quantum :class:`FtdiStreamAdapter` sleeps when the data pipe is
#: empty — pyserial's own ``timeout=0.05`` pacing (``open_serial_port``'s
#: posture), so the :class:`SerialLink` reader thread over the adapter does
#: not hot-spin on pyftdi's immediately-returning empty read.
_IDLE_SLEEP_S = 0.05


def _require_backend() -> Any:
    """Refuse a missing pyftdi with the prefixed install hint, never a bare
    ImportError (the ``open_serial_port`` precedent). Returns the imported
    class so :func:`open_ftdi` never re-imports (one import site)."""
    return _backend()[0]


#: The ONE import site for the whole pyftdi/pyusb backend, test-injectable:
#: ``(Ftdi, UsbTools, usb.core, usb.util, UsbToolsError)`` — the two pyftdi
#: classes the ladder drives, the two pyusb modules the family scan
#: enumerates and reads serial strings through (pyftdi's product tables are
#: never consulted — that is the point), and pyftdi's resolution-class
#: exception, the only class the ladder's fallback is gated on. ``None``
#: means import the real backend.
_BACKEND: Callable[[], tuple[Any, Any, Any, Any, Any]] | None = None


def _backend() -> tuple[Any, Any, Any, Any, Any]:
    if _BACKEND is not None:
        return _BACKEND()
    try:
        # The availability probe EXECUTES the import (not find_spec): a
        # pyftdi present but broken — its pyusb dependency missing — is
        # this refusal's class too, and only the real import proves it.
        import usb.core  # type: ignore[import-untyped]  # pyusb, a pyftdi dependency
        import usb.util  # type: ignore[import-untyped]  # pyusb, a pyftdi dependency
        from pyftdi.ftdi import Ftdi  # type: ignore[import-untyped]  # pyftdi, [server] extra
        from pyftdi.usbtools import (  # type: ignore[import-untyped]  # pyftdi
            UsbTools,
            UsbToolsError,
        )
    except ImportError as exc:
        raise RuntimeError(
            "live_provider_backend_missing: install 'benchweave-sdk[server]' "
            "for ftdi transport support (pyftdi rides the server extra)"
        ) from exc
    return Ftdi, UsbTools, usb.core, usb.util, UsbToolsError


#: One vid/pid-form component: 1-4 hexadecimal digits, ``0x`` optional.
#: The base is EXPLICIT — hexadecimal always (pyftdi's own URL parse reads
#: bare digits as decimal via ``to_int``, which is why the canonical
#: emitted selector always carries the ``0x`` spelling: it reads the same
#: under both parsers).
_HEX_COMPONENT = re.compile(r"\A(?:0x)?[0-9a-fA-F]{1,4}\Z")

#: The colon form's whole grammar (issue #589, rev 7 §2.2): the colon is
#: the VID/PID separator, the serial is the third colon component (a
#: bounded charset that carries no separator of its own), and ``/N`` is the
#: ONLY interface spelling — one accepted string, one parse. A ``/``
#: VID/PID separator made ``0403/dc48/2`` two-parse; ``@N`` was a second
#: spelling of one concept; both are gone.
_VID_PID_FORM = re.compile(
    r"\A(?:0x)?[0-9a-fA-F]{1,4}:(?:0x)?[0-9a-fA-F]{1,4}"
    r"(?::[A-Za-z0-9._-]{1,64})?(?:/[0-9]{1,2})?\Z"
)
#: A bare VID (any product under it, resolved through the registered
#: vendor scan).
_BARE_VID_FORM = re.compile(r"\A(?:0x)?[0-9a-fA-F]{1,4}\Z")
#: The serial charset both forms share.
_SERIAL_CHARS = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
#: The interface path of the URL form (pyftdi's ``?`` listing form would
#: SystemExit a host; this boundary refuses it typed instead).
_INTERFACE_PATH = re.compile(r"\A[0-9]{1,2}\Z")


@dataclass(frozen=True)
class FtdiSelector:
    """One parsed device selector — the operator's ``--device`` value or the
    binding's stored endpoint, in either grammar form. ``port`` is the
    1-BASED interface index (pyftdi's own interface argument is 1-based and
    silently coerces 0 to 1; this boundary refuses 0 instead). ``vid``/
    ``pid`` are ``None`` for an absent component — or, with ``url_form``
    set, for a URL spelling this grammar cannot reduce to a numeric pair (a
    named product, a bus/address form): those pass through to the incumbent
    URL attempt unchanged and simply have no pair for the enumerated
    fallback."""

    raw: str
    vid: int | None
    pid: int | None
    serial: str | None
    port: int
    url_form: bool


def _selector_malformed(raw: str, detail: str) -> RuntimeError:
    return RuntimeError(
        f"live_provider_selector_malformed: {raw!r} is not an FTDI selector "
        f"({detail}); accepted forms: ftdi://0x<vid>:0x<pid>[:<serial>]"
        "[/<interface>], <vid>:<pid>[:<serial>][/<interface>] or a bare "
        "<vid> — hexadecimal ids (0x optional), ':' the vid/pid/serial "
        "separator, '/N' the 1-based interface index"
    )


def _interface_out_of_range(
    raw: str, port: int, ifcount: int | None
) -> RuntimeError:
    bound = (
        f"1..{ifcount} for this device"
        if ifcount is not None
        else "1-based, bounded by the device's interface count"
    )
    return RuntimeError(
        f"live_provider_interface_out_of_range: the selector {raw!r} asks "
        f"for interface {port}; FTDI interface indexes are 1-based ({bound})"
    )


#: One enumerated device row: (vid, pid, serial-or-None, interface_count).
_DeviceRow = tuple[int, int, str | None, int]


def _device_ambiguous(selector: FtdiSelector, rows: list[_DeviceRow]) -> RuntimeError:
    candidates = ", ".join(
        f"0x{vid:04x}:0x{pid:04x}:{serial or 'no-serial'}"
        for vid, pid, serial, _ in rows
    )
    return RuntimeError(
        f"live_provider_device_ambiguous: the selector {selector.raw!r} "
        f"matches {len(rows)} attached devices ({candidates}); add the "
        "device's serial to the selector to pick one"
    )


def _device_unavailable(selector: FtdiSelector, detail: str, note: str = "") -> RuntimeError:
    return RuntimeError(
        f"live_provider_device_unavailable: the FTDI selector "
        f"{selector.raw!r} did not open ({detail}){note}; check the "
        "device's presence, scan again, or pass --device <selector>"
    )


def _hex_component(text: str) -> int:
    """One vid/pid component as hexadecimal (``ValueError`` when the text
    is not one — the caller decides what that means for its form)."""
    if not _HEX_COMPONENT.match(text):
        raise ValueError(f"{text!r} is not 1-4 hexadecimal digits")
    return int(text, 16)


def _parse_ftdi_selector(text: str) -> FtdiSelector:
    """The one parser for both selector forms (issue #589, rev 7 §2.2):

    - The colon form ``vid:pid[:serial][/interface]`` — colon the vid/pid/
      serial separator, ``/N`` the sole interface spelling (1-2 digits,
      1-based), the serial carried VERBATIM (numeric included) in the
      charset ``[A-Za-z0-9._-]{1,64}``; a bare ``vid`` admits any product
      under it. Every accepted string has exactly one parse.
    - The URL form ``ftdi://[vid[:pid[:serial]]]/interface`` — passed
      through to ``open_from_url`` FIRST (the incumbent path). This parser
      reduces it to a numeric pair ONLY when every netloc component is
      expressible in the colon grammar (1-3 non-empty components, the
      first two hexadecimal, the third in the serial charset); a spelling
      beyond that (a named vendor or product, a 4-component bus/address
      form such as ``ftdi://::0x0403:0x6001/1``, a serial with separator
      characters) yields an OPAQUE selector that passes through and simply
      has no pair for the enumerated fallback. A non-index interface path
      is refused here (pyftdi's ``?`` listing form would SystemExit a
      host).

    Port 0 is refused at this boundary with the range named (pyftdi
    silently coerces ``/0`` to 1); a port beyond the device's interface
    count is refused by the ladder once ``ifcount`` is known.
    """
    raw = text.strip()
    if not raw:
        raise _selector_malformed(text, "the selector is empty")
    if raw.lower().startswith("ftdi://"):
        body = raw.split("://", 1)[1]
        netloc, _, path = body.partition("/")
        port = 1
        if path:
            if not _INTERFACE_PATH.match(path):
                raise _selector_malformed(
                    raw,
                    f"the interface path {path!r} is not a 1-2 digit "
                    "1-based index",
                )
            port = int(path)
            if port < 1:
                raise _interface_out_of_range(raw, port, None)
        components = netloc.split(":")
        if 1 <= len(components) <= 3 and all(components):
            try:
                vid = _hex_component(components[0])
                pid = _hex_component(components[1]) if len(components) > 1 else None
            except ValueError:
                # A URL spelling beyond the colon grammar (a named vendor or
                # product) is not an error here — it is the incumbent path's
                # own vocabulary, passed through with no pair for the
                # fallback.
                return FtdiSelector(raw, None, None, None, port, True)
            serial = components[2] if len(components) > 2 else None
            if serial is None or _SERIAL_CHARS.match(serial):
                return FtdiSelector(raw, vid, pid, serial, port, True)
        # An empty component, a 4-component bus/address form, or a serial
        # the colon charset cannot express: opaque passthrough, exactly as
        # pyftdi's own grammar reads the form.
        return FtdiSelector(raw, None, None, None, port, True)
    if _BARE_VID_FORM.match(raw):
        return FtdiSelector(raw, _hex_component(raw), None, None, 1, False)
    if not _VID_PID_FORM.match(raw):
        raise _selector_malformed(
            raw,
            "expected <vid>:<pid>[:<serial>][/<interface>] or a bare <vid> "
            "with hexadecimal ids, ':' the separator and '/N' the 1-based "
            "interface",
        )
    pair_part, _, suffix = raw.partition("/")
    port = int(suffix) if suffix else 1
    if port < 1:
        raise _interface_out_of_range(raw, port, None)
    components = pair_part.split(":")
    return FtdiSelector(
        raw,
        _hex_component(components[0]),
        _hex_component(components[1]),
        components[2] if len(components) > 2 else None,
        port,
        False,
    )


class _PyftdiDriver:
    """The real driver: pyftdi's ``Ftdi`` behind the executor's protocol
    names. The only class that knows pyftdi's call names; ``open_ftdi`` is
    the only constructor path.

    Two mapping rules the refute lane's F1/F3a arms pin: ``set_bitmode``
    COERCES the transaction's int mode into pyftdi's ``BitMode`` enum
    (pyftdi 0.57 dereferences ``mode.name`` first — a raw int raises
    AttributeError before any USB call, unservable on a device); and an
    unknown ``purge`` queue refuses typed BEFORE I/O, never defaulting to
    a queue the caller did not ask for.
    """

    def __init__(self, ftdi: Any) -> None:
        self._ftdi = ftdi
        self._bitmode_cls = ftdi.BitMode

    def reset_device(self) -> None:
        self._ftdi.reset()

    def set_timeouts(self, read_ms: int, write_ms: int) -> None:
        self._ftdi.timeouts = (read_ms, write_ms)

    def set_latency(self, ms: int) -> None:
        self._ftdi.set_latency_timer(ms)

    def set_baud(self, baud: int) -> None:
        self._ftdi.set_baudrate(baud)

    def purge(self, queue: str) -> None:
        if queue == "tx":
            self._ftdi.purge_tx_buffer()
        elif queue == "rx":
            self._ftdi.purge_rx_buffer()
        else:
            raise ValueError(
                f"live_provider_transaction_grammar: purge queue {queue!r} "
                "is not in the contract's declared enum ('tx' or 'rx')"
            )

    def set_bitmode(self, mask: int, mode: int) -> None:
        self._ftdi.set_bitmode(mask, self._bitmode_cls(mode))

    def read_pins(self) -> int:
        return int(self._ftdi.read_pins())

    def write_data(self, data: bytes) -> int:
        return int(self._ftdi.write_data(bytes(data)))

    def read_data(self, size: int) -> bytes:
        return bytes(self._ftdi.read_data(size))

    def close(self) -> None:
        self._ftdi.close()


def _registered_vendor_ids() -> frozenset[int]:
    """The vendor ids every registered provider family scans — the
    auto-discovery scope (a vendor no executor registers stays out of the
    pick flow until an operator names a device by selector; that is the
    family-registry model, not a per-device special case)."""
    return frozenset(
        vid for executor in PROVIDER_EXECUTORS.values() for vid in executor.vendor_ids
    )


def _scan_vendor_rows(
    usb_core: Any, usb_util: Any, vendor: int
) -> list[tuple[int, int, str | None, int]]:
    """One vendor's devices at the pyusb level — ``(vid, pid, serial,
    ifcount)`` rows; pyftdi's product tables are never consulted (that is
    the point: the table gate that broke every OEM URL form cannot break a
    scan that never reads the table)."""
    rows: list[tuple[int, int, str | None, int]] = []
    for dev in usb_core.find(find_all=True, idVendor=vendor):
        ifcount = max(
            (int(getattr(cfg, "bNumInterfaces", 0) or 0) for cfg in dev), default=0
        )
        serial: str | None = None
        string_index = int(getattr(dev, "iSerialNumber", 0) or 0)
        if string_index:
            reported = usb_util.get_string(dev, string_index)
            if isinstance(reported, str) and reported:
                serial = reported
        rows.append(
            (int(dev.idVendor), int(dev.idProduct), serial, max(ifcount, 1))
        )
    return rows


def _pid_unregistered(ftdi_cls: Any, vid: int, pid: int) -> bool:
    table = ftdi_cls.PRODUCT_IDS.get(vid)
    return table is None or pid not in table.values()


def open_ftdi(url: str) -> FtdiDriver:
    """Open one FTDI-class device by its selector (the ``--device``
    spelling, e.g. ``ftdi://0x0403:0x6001/1`` or ``0403:6001/1`` — the
    grammar and the 1-based interface index are :func:`_parse_ftdi_selector`'s).

    The resolution ladder (issue #589): the URL form is tried through
    pyftdi's ``open_from_url`` first — the incumbent path, with the
    selector's OWN vid/pid pair registered for the attempt (an OEM pair
    absent from pyftdi's static product table is the table gate that made
    every URL form fail) and the class table RESTORED after it in a
    ``finally``, because pyftdi 0.57.2 has no removal API and a leaked row
    makes a later joker-URL enumeration see the pair. A resolution-class
    failure (``UsbToolsError`` — table gate, no match, a refused serial)
    falls through to an enumerated fallback: ``UsbTools.find_all`` over the
    parsed pair with ``nocache=True`` (the bus as it is now), the selector's
    serial honoured always, twins refused with every candidate named, the
    interface validated against the device's own interface count before the
    one direct ``open``. A bare-VID selector enumerates the registered
    vendor scan instead (``find_all``'s None-pid search is structurally
    empty). A claim-time failure (busy, permission — any non-resolution
    exception) refuses immediately: still ONE bounded open attempt, zero
    retries of a failed OPEN (A06); selector RESOLUTION may enumerate once.

    A missing pyftdi refuses ``live_provider_backend_missing:``; every open
    failure refuses ``live_provider_device_unavailable:`` naming the
    selector, the failing class and the enumeration result. The refusals
    are ``RuntimeError`` so the session's connect path passes them through
    unwrapped for the seam to map ``not_ready``.
    """
    ftdi_cls, usbtools, usb_core, usb_util, usbtools_error = _backend()
    selector = _parse_ftdi_selector(url)
    ftdi = ftdi_cls()
    url_failure: BaseException | None = None
    registered_note = ""
    if selector.url_form:
        vid, pid = selector.vid, selector.pid
        pair_known = vid is not None and pid is not None
        saved = (
            OrderedDict(ftdi_cls.PRODUCT_IDS[vid])
            if pair_known and vid in ftdi_cls.PRODUCT_IDS
            else None
        )
        transient = False
        if (
            pair_known
            and vid is not None
            and pid is not None
            and _pid_unregistered(ftdi_cls, vid, pid)
        ):
            ftdi_cls.add_custom_product(vid, pid)
            transient = True
        try:
            ftdi.open_from_url(url)
            return _PyftdiDriver(ftdi)
        except Exception as exc:
            with contextlib.suppress(Exception):
                ftdi.close()
            if transient and selector.vid is not None and selector.pid is not None:
                registered_note = (
                    f"; the selector's own pair 0x{selector.vid:04x}:"
                    f"0x{selector.pid:04x} was registered for the URL "
                    "attempt and removed again"
                )
            if not isinstance(exc, usbtools_error):
                raise _device_unavailable(
                    selector, f"URL attempt: {type(exc).__name__}", registered_note
                ) from exc
            url_failure = exc
        finally:
            # Restore, not merge: the per-vid row is mutated in place, so
            # the save above COPIED it — restoring the live object would
            # restore the post-registration state and prove nothing.
            if pair_known:
                if saved is None:
                    ftdi_cls.PRODUCT_IDS.pop(selector.vid, None)
                else:
                    ftdi_cls.PRODUCT_IDS[selector.vid] = saved
    # The enumerated fallback (resolution-class URL failures and the colon
    # form). One open attempt at the end of it, zero retries.
    try:
        if selector.vid is None:
            # An opaque URL spelling (named vendor, bus/address form) has no
            # pair to enumerate: the incumbent attempt above was the open.
            detail = (
                f"URL attempt: {type(url_failure).__name__}"
                if url_failure is not None
                else "the URL form did not open"
            )
            raise _device_unavailable(selector, detail, registered_note)
        if selector.pid is None:
            if selector.vid in _registered_vendor_ids():
                rows = _scan_vendor_rows(usb_core, usb_util, selector.vid)
            else:
                rows = []
        else:
            rows = [
                (int(d.vid), int(d.pid), (str(d.sn) if d.sn else None), int(ifcount))
                for d, ifcount in usbtools.find_all(
                    [(selector.vid, selector.pid)], nocache=True
                )
            ]
    except RuntimeError:
        raise
    except Exception as exc:
        raise _device_unavailable(
            selector, f"enumeration: {type(exc).__name__}", registered_note
        ) from exc
    if selector.serial is not None:
        rows = [row for row in rows if row[2] == selector.serial]
    if not rows:
        hint = ""
        if selector.pid is None and selector.vid not in _registered_vendor_ids():
            hint = (
                f" — the bare-VID scan covers registered provider families "
                f"only; qualify vendor 0x{selector.vid:04x} with a pid"
            )
        detail = "enumeration found 0 matching device(s)" + hint
        if url_failure is not None:
            detail = (
                f"URL attempt: {type(url_failure).__name__}; " + detail
            )
        raise _device_unavailable(selector, detail, registered_note)
    if len(rows) > 1:
        raise _device_ambiguous(selector, rows)
    device_vid, device_pid, _, ifcount = rows[0]
    if not 1 <= selector.port <= ifcount:
        raise _interface_out_of_range(selector.raw, selector.port, ifcount)
    try:
        ftdi.open(
            device_vid, device_pid, serial=selector.serial, interface=selector.port
        )
    except Exception as exc:
        with contextlib.suppress(Exception):
            ftdi.close()
        raise _device_unavailable(
            selector, f"open: {type(exc).__name__}", registered_note
        ) from exc
    return _PyftdiDriver(ftdi)


class _ScriptEntry:
    """One parsed script row: a control expectation (op + params + the
    scripted ``read_pins`` answer) or a stream expectation (the exact
    request bytes and the reply bytes the ``write`` releases)."""

    __slots__ = ("name", "op", "params", "pins_answer", "request", "response")

    def __init__(
        self,
        name: str,
        *,
        op: str | None = None,
        params: dict[str, Any] | None = None,
        pins_answer: int | None = None,
        request: bytes | None = None,
        response: bytes = b"",
    ) -> None:
        self.name = name
        self.op = op
        self.params = params
        self.pins_answer = pins_answer
        self.request = request
        self.response = response


class ScriptedFtdiDriver:
    """The committed rehearsal double at the driver boundary (the design
    record's §3, the 2026-10-28 ruling: mock parity rides in the slice as a
    SHIPPED component, not a test helper).

    The constructor takes a script in the #564 journal's row shape —
    ``[{"name": ..., "transaction": {...}, "response": {...}}, ...]``. A row
    whose ``transaction`` carries an ``op`` is a control row (the expected
    op and params; a ``response.data`` base64 byte is the scripted
    ``read_pins`` answer); a stream row's hex ``data`` is the exact request
    a ``write`` must carry and its ``response.data`` the reply the write
    releases to the data pipe; a response-only stream row releases its
    reply at construction (a device-initiated frame). Every call is
    recorded; each call must match the head of the remaining script or the
    double refuses with :class:`ConformanceError` naming the row and the
    call — the exact-match discipline, one boundary down from the mock
    host's. ``fault_writes`` turns every later ``write_data`` into the
    mid-conversation unplug fault (the faulted-posture rehearsal).

    A plugin author rehearses without hardware by driving the production
    session over this double; the operator-facing recorded rehearsal stays
    the replay transport (#564) — neither claims to be the other, and no
    device behavior is claimed or proven here.
    """

    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.writes: list[bytes] = []
        self.write_calls = 0
        self.closes = 0
        self.fault_writes = False
        self.fault_reads = False
        self.short_writes = False
        self._write_done = False
        self._script: deque[_ScriptEntry] = deque()
        self._inbound = bytearray()
        for index, row in enumerate(rows):
            self._script.append(self._parse_row(row, index))
            # A response-only stream row is a device-initiated frame: it is
            # on the pipe from the start, exactly as a device that speaks
            # first would be.
            entry = self._script[-1]
            if entry.op is None and entry.request is None and entry.response:
                self._inbound += self._script.pop().response

    def _parse_row(self, row: Mapping[str, Any], index: int) -> _ScriptEntry:
        def malformed(detail: str) -> ValueError:
            return ValueError(
                f"scripted_driver_row: row {index}: {detail} (the script "
                "carries the #564 journal row shape)"
            )

        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise malformed("name is not a non-empty string")
        transaction = row.get("transaction")
        if not isinstance(transaction, dict):
            raise malformed("transaction is not an object")
        response = row.get("response", {})
        if not isinstance(response, dict):
            raise malformed("response is not an object")
        if "op" in transaction:
            params = {
                key: value
                for key, value in transaction.items()
                if key not in ("kind", "op")
            }
            entry = _ScriptEntry(name, op=str(transaction["op"]), params=params)
            if transaction["op"] == "read_pins":
                answer = response.get("data")
                if not isinstance(answer, str):
                    raise malformed(
                        "a read_pins row's response carries a base64 'data' byte"
                    )
                try:
                    decoded = base64.b64decode(answer, validate=True)
                except ValueError as exc:
                    raise malformed(
                        f"the read_pins answer {answer!r} is not valid base64"
                    ) from exc
                if not decoded:
                    raise malformed("the read_pins answer carries no bytes")
                entry.pins_answer = int.from_bytes(decoded, "big")
            return entry
        kind = transaction.get("kind")
        if kind not in ("stream_send", "stream_exchange", "stream_receive"):
            raise malformed(
                f"kind {kind!r} is neither a control row (an 'op') nor a "
                "section 8.1 stream kind"
            )
        if kind == "stream_receive":
            if "data" in transaction:
                raise malformed("a receive row carries no outgoing data")
            return _ScriptEntry(name)
        data = transaction.get("data")
        if isinstance(data, bytes):
            # The ABI spelling (a builder's own transaction dict) is
            # accepted beside the journal's hex form — both are exact.
            request = data
        elif isinstance(data, str):
            try:
                request = bytes.fromhex(data)
            except ValueError as exc:
                raise malformed(
                    f"the stream data {data!r} is not a hex byte string"
                ) from exc
        else:
            raise malformed(
                "a stream row's data is a hex byte string or bytes"
            )
        reply = response.get("data", "")
        if not isinstance(reply, (str, bytes)):
            raise malformed("a stream row's response data is a hex byte string")
        try:
            response_bytes = reply if isinstance(reply, bytes) else bytes.fromhex(reply)
        except ValueError as exc:
            raise malformed(
                f"the stream response {reply!r} is not a hex byte string"
            ) from exc
        return _ScriptEntry(name, request=request, response=response_bytes)

    # -- the exact-match core --------------------------------------------------

    def _next(self, call: str) -> _ScriptEntry:
        if not self._script:
            raise ConformanceError(
                f"scripted driver: the script is exhausted at call {call!r} — "
                "the conversation ran past its recording"
            )
        return self._script[0]

    def _control(self, op: str, params: dict[str, Any]) -> Any:
        entry = self._next(op)
        if entry.op != op or entry.params != params:
            raise ConformanceError(
                f"scripted driver: row {entry.name!r} expects "
                f"{entry.op} {entry.params}, got {op} {params}"
            )
        self._script.popleft()
        self.calls.append((op, dict(params)))
        return entry.pins_answer

    def reset_device(self) -> None:
        self._control("reset_device", {})

    def set_timeouts(self, read_ms: int, write_ms: int) -> None:
        self._control("set_timeouts", {"read_ms": read_ms, "write_ms": write_ms})

    def set_latency(self, ms: int) -> None:
        self._control("set_latency", {"ms": ms})

    def set_baud(self, baud: int) -> None:
        self._control("set_baud", {"baud": baud})

    def purge(self, queue: str) -> None:
        self._control("purge", {"queue": queue})

    def set_bitmode(self, mask: int, mode: int) -> None:
        self._control("set_bitmode", {"mask": mask, "mode": mode})

    def read_pins(self) -> int:
        answer = self._control("read_pins", {})
        assert isinstance(answer, int)  # a read_pins row always carries an answer
        return answer

    def write_data(self, data: bytes) -> int:
        self.write_calls += 1
        if self.fault_writes:
            raise OSError("device unplugged")
        entry = self._next("write_data")
        if entry.request != bytes(data):
            raise ConformanceError(
                f"scripted driver: row {entry.name!r} expects the frame "
                f"{entry.request.hex() if entry.request is not None else '<none>'}, "
                f"got {bytes(data).hex()}"
            )
        self._script.popleft()
        self.writes.append(bytes(data))
        self._inbound += entry.response
        self._write_done = True
        if self.short_writes and len(data) > 4:
            # A short count: part of the frame hit the pipe; the services
            # layer's own short-count refusal judges it.
            return 4
        return len(data)

    def read_data(self, size: int) -> bytes:
        if self.fault_reads and self._write_done:
            # The F5 shape: the frame went out, then the receive faults.
            raise OSError("device unplugged mid-receive")
        out = bytes(self._inbound[:size])
        del self._inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1


class FtdiStreamAdapter:
    """pyserial's ``write``/``read``/``close`` surface over the driver's
    data pipe, so :class:`SerialLink` and its whole receive ladder (the
    quiet line, terminator search, retained partial, drain-then-refuse on
    close) are reused verbatim — no new ring, no new ladder.

    ``write`` returns the sent count: a short count propagates and the
    backend's own short-count refusal judges it. ``read`` asks the driver
    for what is ALREADY buffered — pyftdi's ``read_data`` returns at once,
    empty when nothing has arrived (the #589 bench measurement: an empty
    ``read_data(4096)`` answers ``b''`` in under a millisecond; the chip
    always answers bulk IN with modem-status bytes inside the latency
    timer, so the driver never blocks the way a pyserial ``timeout=0.05``
    read would) — and the ADAPTER's idle sleep is the whole pacing, so the
    reader thread never hot-spins. ``close`` closes the driver — the one
    device handle.
    """

    def __init__(self, driver: FtdiDriver) -> None:
        self._driver = driver
        #: Whether the LAST write left the driver in full (the recorder's
        #: F5 discriminator: only a fully-sent frame's request row may
        #: land on a later receive fault — a partial never claims to have
        #: gone out whole).
        self.completed = False
        #: The reply-follows-request wake (the macOS CI failure's fix):
        #: a full write sets this event, so the reader thread's pending
        #: idle wait returns IMMEDIATELY instead of sleeping out its
        #: quantum — the stream reply's delivery margin is the whole
        #: quiet window, not the window minus the quantum. A missed wake
        #: (set between the reader's clear and its next wait) costs one
        #: quantum, exactly the pre-fix latency — the event widens the
        #: margin, never narrows it. The reply-follows-request causality
        #: holds for the real device too: the wake makes the reader poll
        #: once more per write; a device with nothing yet in the pipe
        #: answers empty and the reader parks again (no hot spin — one
        #: immediate poll per write).
        self._wake = threading.Event()

    def write(self, data: bytes) -> int | None:
        self.completed = False
        sent = self._driver.write_data(data)
        self.completed = sent == len(data)
        if self.completed:
            self._wake.set()
        return sent

    def read(self, size: int = 1) -> bytes:
        data = self._driver.read_data(size)
        if not data:
            self._wake.wait(_IDLE_SLEEP_S)
            self._wake.clear()
        return data

    def close(self) -> None:
        self._driver.close()


class FtdiCaptureServices(SerialCaptureServices):
    """All the capture members plus the live provider ladder over one FTDI
    device: the serial backend's services with the provider dispatch
    grafted in front of the stream path.

    Constructor notes versus the parent: ``reconfigurator`` is
    deliberately absent — on this transport a baud change is a PROVIDER
    transaction (``set_baud``), not a link-control swap, so
    ``reconfigure_link`` degrades loudly to its typed not-configured
    refusal and ``link_state`` answers ``None`` (the correct permanent
    posture, design §7.7). ``grammar`` is the compiled pinned grammar the
    provider path validates through; ``provider`` is the pinned contract's
    triple (feature id and digest reach the capture sidecar).
    """

    def __init__(
        self,
        link: SerialLink,
        driver: FtdiDriver,
        grammar: dict[str, GrammarEntry],
        *,
        provider: dict[str, str],
        max_frame_bytes: int,
        capture_root: Any = None,
        capture_max_bytes: int | None = None,
        limits: Mapping[str, Any] | None = None,
        rehearsal: bool = False,
        ops: Mapping[str, tuple[str, ...]] | None = None,
        byte_answer_ops: Iterable[str] | None = None,
    ) -> None:
        super().__init__(
            link,
            max_frame_bytes=max_frame_bytes,
            capture_root=capture_root,
            capture_max_bytes=capture_max_bytes,
        )
        self._driver = driver
        self._grammar = grammar
        self._provider = dict(provider)
        self._limits = dict(limits or {})
        #: The op dispatch table (E1): the EXECUTOR's table, injected —
        #: the module-level FTDI table was the admission/serving gap.
        self._ops = dict(ops) if ops is not None else dict(_OPS)
        #: The executor's byte-answer ops (see ProviderExecutor's field
        #: comment for why the grammar cannot discriminate) — the
        #: contract's set, falling back to the FTDI family's for direct
        #: construction.
        self._byte_answer_ops = frozenset(byte_answer_ops or {"read_pins"})
        #: Whether this session runs over the SHIPPED SCRIPTED DOUBLE
        #: rather than live hardware (the acceptance review's A): the
        #: marker reaches the capture sidecar and the mode banner — a
        #: rehearsal must never read as a live device.
        self.rehearsal = rehearsal
        # The faulted-driver latch (refute lane A, F6): a driver exception
        # latches THIS connection's services — every later transaction
        # refuses ConnectionError before the driver. "A faulted driver
        # stays faulted" is enforced, not claimed; a reconnect mints fresh
        # services (the M1 fold's fresh conversation).
        self._faulted = False
        self._write_label = "ftdi"

    # -- capture (the sidecar names the transport and the contract) --------

    def configure_capture(
        self,
        capture_id: str,
        *,
        metadata: dict[str, Any],
        max_bytes: int | None = None,
    ) -> None:
        """Arm the capture with the provider evidence composed INTO the
        sidecar (the replay host's precedent: the durable evidence names
        what served — the transport, the contract revision that governed
        its wire grammar, and — when the session runs over the shipped
        scripted double — the rehearsal marker. A capture over a double
        must never read as a live hardware capture: ``config.rehearsal``
        names it, mirroring replay's ``replay_journal`` block)."""
        config = metadata.get("config")
        stamped_config: dict[str, Any] = {
            **(config if isinstance(config, dict) else {}),
            "transport": "ftdi",
            "provider": {
                "feature_id": self._provider["feature_id"],
                "sha256": self._provider["sha256"],
            },
        }
        if self.rehearsal:
            stamped_config["rehearsal"] = {"driver": "scripted"}
        stamped = dict(metadata, config=stamped_config)
        super().configure_capture(capture_id, metadata=stamped, max_bytes=max_bytes)

    # -- the provider ladder -------------------------------------------------

    def _validate_provider(self, transaction: dict[str, Any]) -> None:
        """Grammar-first refusal: one provider transaction against the
        ADMITTED grammar, in document form (bytes become base64 text, the
        contract's own spelling). Refused before any state change (replay's
        ``_validate_provider`` verbatim in shape, the live prefix)."""
        entry = self._grammar[transaction["kind"]]
        document = {
            key: (
                base64.b64encode(value).decode("ascii")
                if key in entry.request_b64 and isinstance(value, bytes)
                else value
            )
            for key, value in transaction.items()
            if key != "kind"
        }
        error = _first_schema_error(entry.request_validator, document)
        if error is not None:
            raise ValueError(
                f"live_provider_transaction_grammar: the transaction does not "
                f"satisfy the admitted {transaction['kind']} grammar: {error}"
            )

    #: The FTDI family's BitMode byte encoding (the public hardware
    #: enum: RESET/BITBANG/MPSSE/SYNCBB/MCU/OPTO/CBUS/SYNCFF = 0..1
    #: powers of two up to 0x40). The contract's limits admit mode 0..255,
    #: but the family's byte expresses these eight values only — an
    #: inadmissible mode must refuse TYPED before the driver call (F3a's
    #: principle), never reach the coercion and fault the connection for a
    #: parameter-domain error (the delta refute's residual 2).
    _ADMISSIBLE_BITMODES = frozenset({0, 1, 2, 4, 8, 16, 32, 64})

    #: The contract's limits keys to the transaction parameters they
    #: bound (only keys the contract DECLARES are enforced — A02: the
    #: contract's declaration governs, never a host constant).
    _LIMIT_RANGES: Mapping[str, tuple[str, ...]] = {
        "set_timeouts_ms_range": ("read_ms", "write_ms"),
        "set_latency_ms_range": ("ms",),
        "set_bitmode_mask_range": ("mask",),
        "set_bitmode_mode_range": ("mode",),
    }

    def _enforce_limits(self, transaction: dict[str, Any]) -> None:
        """Refuse a transaction whose values sit outside the contract's
        declared limits, before any state change and before the driver
        call — an admitted-but-unexpressible value never dispatches."""
        op = transaction.get("op")
        for key, names in self._LIMIT_RANGES.items():
            bound = self._limits.get(key)
            if not (isinstance(bound, list) and len(bound) == 2):
                continue
            low, high = int(bound[0]), int(bound[1])
            for name in names:
                value = transaction.get(name)
                if isinstance(value, int) and not isinstance(value, bool) and not (
                    low <= value <= high
                ):
                    raise ValueError(
                        f"live_provider_transaction_grammar: {op} {name}={value} "
                        f"is outside the contract's declared limit {key} "
                        f"[{low}, {high}]"
                    )
        minimum = self._limits.get("set_baud_minimum")
        if isinstance(minimum, int) and op == "set_baud":
            baud = transaction.get("baud")
            if isinstance(baud, int) and not isinstance(baud, bool) and baud < minimum:
                raise ValueError(
                    f"live_provider_transaction_grammar: set_baud baud={baud} "
                    f"is below the contract's declared set_baud_minimum "
                    f"{minimum}"
                )
        mode = transaction.get("mode")
        if (
            op == "set_bitmode"
            and isinstance(mode, int)
            and not isinstance(mode, bool)
            and mode not in self._ADMISSIBLE_BITMODES
        ):
            raise ValueError(
                f"live_provider_transaction_grammar: set_bitmode "
                f"mode={mode} is outside the FTDI family's BitMode byte "
                f"values {sorted(self._ADMISSIBLE_BITMODES)}"
            )

    def _dispatch(self, op: str, args: list[Any]) -> Any:
        """One driver call by op name (the table is the authority)."""
        return getattr(self._driver, op)(*args)

    async def transfer(
        self, transaction: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        """The ladder: the pinned grammar's kinds dispatch onto the driver;
        everything else is the parent's own section 8.1 stream path — whose
        grammar gate refuses what is neither, unchanged."""
        kind = transaction.get("kind")
        if not (isinstance(kind, str) and kind in self._grammar):
            # The latch gates the STREAM path as well (the delta refute's
            # residual 1): after a fault, a later stream transaction must
            # refuse before the driver exactly like a provider one. The
            # check sits at the branch's head so no stream call reaches
            # the driver on a faulted connection.
            if self._faulted:
                raise ConnectionError(
                    "the ftdi driver previously faulted on this "
                    "connection; reconnect required"
                )
            try:
                return await super().transfer(transaction, context)
            except ConnectionError:
                # F6's latch covers the stream side too: a faulted driver
                # (including a faulted link) stays faulted on this
                # connection; every later transaction refuses before
                # dispatch until a reconnect mints fresh services.
                self._faulted = True
                raise
        # 1. Grammar first, before any state change: the schema, then the
        #    contract's declared limits (F3b — the schema alone admits
        #    values the device cannot express; the limits block is the
        #    contract's own envelope).
        self._validate_provider(transaction)
        self._enforce_limits(transaction)
        # 2. The closed posture (the driver shares the link's close path),
        #    and the faulted-driver latch (F6).
        if self._faulted:
            raise ConnectionError(
                "the ftdi driver previously faulted on this connection; "
                "reconnect required"
            )
        if self._link.is_closed:
            raise ConnectionError("ftdi device link is closed")
        # 3. The busy guard (the #407 guard one mode over, uniform over all
        #    control ops — maintainer ruling 3): a control op that changes
        #    line semantics under a parked receive would corrupt the very
        #    bytes the receive is waiting on. The visibility bound is the
        #    guard's own (#407's disclosed window: read at worker-start,
        #    not dispatch).
        if self._link.receive_depth > 0:
            raise ValueError(
                "live_provider_line_busy: a stream receive is parked on this "
                "device; a control transaction would change the line "
                "semantics under it — let the receive finish or expire first"
            )
        # 4. Liveness, then the dispatch marker (a control transmit is a
        #    transmit — the mock's discipline on the real backend, A06).
        self._live(context)
        if not getattr(context, "dispatched", False):
            raise ConformanceError("Transmission needs a dispatch marker")
        # 5. Dispatch: the table is the vocabulary (the version-skew belt).
        op = transaction.get("op")
        if not isinstance(op, str) or op not in self._ops:
            raise ValueError(
                f"live_provider_op_unknown: op {op!r} is not in this "
                "executor's op table; the pinned contract may be newer than "
                "the SDK — upgrade the SDK to serve it"
            )
        params = self._ops[op]
        args = [transaction[name] for name in params]
        # One bounded attempt, never a retry (A06): a driver exception maps
        # to ConnectionError naming the class — a faulted driver stays
        # faulted, reconnect required.
        try:
            result = await asyncio.to_thread(self._dispatch, op, args)
        except Exception as exc:
            self._faulted = True
            raise ConnectionError(
                f"ftdi driver call failed: {type(exc).__name__}: {exc}"
            ) from exc
        # 6. Result validation: the live device is untrusted against its
        #    own pinned contract. read_pins wraps its byte in the base64
        #    document form and validates; actuation ops answer {} —
        #    transport acceptance carries no device meaning (the contract's
        #    own result-schema wording).
        entry = self._grammar[kind]
        if op in self._byte_answer_ops:
            # A byte-answer op (the FTDI family's read_pins; any family
            # whose result schema declares a base64 "data" property): the
            # driver's one-byte answer is validated against the admitted
            # result schema — the live device is untrusted against its
            # own pinned contract.
            if not isinstance(result, int) or isinstance(result, bool) or not (
                0 <= result <= 255
            ):
                raise ValueError(
                    f"live_provider_result_grammar: op {op!r} answered "
                    f"{result!r}, which is not the one byte the admitted "
                    "result schema declares"
                )
            document = {"data": base64.b64encode(bytes([result])).decode("ascii")}
            error = _first_schema_error(entry.result_validator, document)
            if error is not None:
                raise ValueError(
                    f"live_provider_result_grammar: the device's {op!r} "
                    f"answer does not satisfy the admitted {kind} grammar: "
                    f"{error}"
                )
            return {"data": bytes([result])}
        return {}


def _ftdi_pinned_contract(plugin: LoadedPlugin) -> tuple[dict[str, Any], str]:
    """The plugin's pinned, verified provider contract and the digest of
    its bytes — the same two operations replay's ``_pinned_contract``
    performs, with THIS transport's unpinned refusal: a plugin that
    declares no provider cannot land on the live provider transport (a
    stream plugin belongs on the serial transport). The check lane's own
    ``provider_*:`` refusals ride out unchanged either way."""
    from benchweave_sdk.validation import verify_provider_pin

    descriptor_path = plugin.package_dir / "descriptor.json"
    pinned = verify_provider_pin(plugin.descriptor, descriptor_path)
    if pinned is None:
        raise ValueError(
            "live_provider_plugin_unpinned: the live provider transport "
            "serves the pinned contract's provider transactions; this "
            "plugin's descriptor declares no transport provider — a stream "
            "plugin belongs on the serial transport, or pin the contract"
        )
    relative = plugin.descriptor["transport"]["provider"]["path"]
    digest = hashlib.sha256((plugin.package_dir / relative).read_bytes()).hexdigest()
    return pinned, digest


@dataclass(frozen=True)
class ProviderExecutor:
    """One provider family's executor descriptor (row e, the owner
    expansion): everything the transport needs to serve a family, so a
    second family plugs in by REGISTERING one of these — the transport's
    machinery (the services ladder, the seam wiring, the CLI branch) is
    family-agnostic and does not edit per family.

    The anti-laundering bind rides the executor UNCHANGED: the pinned
    contract must be digest-equal to the BANKED instance the executor's
    ``banked_path`` resolves — generalising the registry did not weaken
    the gate (the lookalike arms pin both families).
    """

    family: str
    feature_prefix: str
    transport_kind: str
    probe_payloads: Mapping[str, dict[str, Any]]
    #: The op dispatch table (E1, the mechanism refute): the executor
    #: supplies the table so a registered family SERVES through the
    #: transport, not merely admits — the module-level table was the
    #: admission/serving gap.
    ops: Mapping[str, tuple[str, ...]]
    #: The family's byte-answer ops: the driver returns one byte, the
    #: result validates against the admitted schema in base64 document
    #: form. The FTDI contract's result schema is shared across its
    #: seven ops (an empty branch and a data branch), so the GRAMMAR
    #: cannot discriminate per op — the executor declares the set.
    byte_answer_ops: frozenset[str] = frozenset({"read_pins"})
    #: The banked-instance resolver: the packaged providers directory by
    #: default; a test-only family points its own banked copy (the
    #: registry's honesty constraint — exactly one real family exists).
    banked_resolver: Callable[[str], Path | None] | None = None
    #: The vendor ids this family's AUTO-DISCOVERY scans (pyusb-level; the
    #: registry is the anti-laundering gate — a vendor no executor
    #: registers stays out of the pick flow until an operator names a
    #: device by selector). The one sanctioned home of a family's device
    #: identity: the generality gate counts these literals where they
    #: live, inside the PROVIDER_EXECUTORS registration block.
    vendor_ids: tuple[int, ...] = ()

    def banked_path(self, tail: str) -> Path | None:
        """The banked contract instance for one feature version tail."""
        if self.banked_resolver is not None:
            return self.banked_resolver(tail)
        from importlib.resources import files

        banked = files("benchweave_sdk").joinpath(
            "providers", f"{self.family}-control-{tail}.json"
        )
        candidate = Path(str(banked))
        return candidate if candidate.is_file() else None


#: The registry (row e): the FTDI family is the one production member —
#: exactly one real family exists, so the registry's second exerciser is a
#: TEST-ONLY family registered by the suite, never a fabricated production
#: contract. A family registers here; nothing in the transport names a
#: family inline.
PROVIDER_EXECUTORS: dict[str, ProviderExecutor] = {
    "ftdi": ProviderExecutor(
        family="ftdi",
        feature_prefix=_FEATURE_PREFIX,
        transport_kind="ftdi",
        probe_payloads=_PROBE_PAYLOADS,
        ops=_OPS,
        # FTDI's own vendor id — the family's, printed in the user guide's
        # example selectors; never any device's product id or serial (the
        # generality gate counts this block's literals).
        vendor_ids=(0x0403,),
    ),
}


def executor_for(pinned: dict[str, Any]) -> ProviderExecutor | None:
    """The executor whose feature family the pinned contract declares (or
    None — the caller refuses live_provider_feature_unsupported)."""
    feature_id = pinned.get("feature_id")
    if not isinstance(feature_id, str):
        return None
    for executor in PROVIDER_EXECUTORS.values():
        if feature_id.startswith(executor.feature_prefix):
            return executor
    return None


def _require_ftdi_feature(pinned: dict[str, Any], digest: str) -> None:
    """The identity half of the served-set bind — and the anti-laundering
    gate (refute lane A, F2): the pinned contract must declare the banked
    FTDI common control feature family (``otdp.transport.ftdi-control/
    <semver>``) AND its bytes must BE the banked instance for that version
    (digest-equal). A feature-id prefix alone launders an unreviewed
    contract's semantics under an approved name; a version tail with no
    banked instance is not served at all."""
    feature_id = pinned.get("feature_id")
    executor = executor_for(pinned)
    if executor is None or not (
        isinstance(feature_id, str)
        and _SEMVER.match(feature_id[len(executor.feature_prefix) :])
    ):
        families = ", ".join(
            f"{row.feature_prefix}<semver>" for row in PROVIDER_EXECUTORS.values()
        )
        raise ValueError(
            f"live_provider_feature_unsupported: this transport serves "
            f"registered provider families ({families}); the pinned "
            f"contract declares {feature_id!r} — pin a banked contract or "
            "serve this plugin on its own transport"
        )
    tail = feature_id[len(executor.feature_prefix) :]
    banked = executor.banked_path(tail)
    if banked is None:
        raise ValueError(
            f"live_provider_feature_unsupported: no banked "
            f"{executor.family} control contract exists for version "
            f"{tail}; this executor serves banked feature lines only"
        )
    banked_digest = hashlib.sha256(banked.read_bytes()).hexdigest()
    if digest != banked_digest:
        raise ValueError(
            f"live_provider_feature_unsupported: the pinned contract for "
            f"{feature_id} hashes to sha256 {digest} but the banked "
            f"instance hashes to {banked_digest}; this transport serves "
            "the banked bytes only — pin the banked contract"
        )


def _banked_contract_path(tail: str) -> Any:
    """The banked contract instance for one feature version tail, or None
    when this SDK banks no such version."""
    from importlib.resources import files

    banked = files("benchweave_sdk").joinpath("providers", f"ftdi-control-{tail}.json")
    return banked if Path(str(banked)).is_file() else None


def _probe_grammar(pinned: dict[str, Any]) -> dict[str, GrammarEntry]:
    """Compile the pinned grammar and probe every op in the dispatch table
    against it — the surface half of the served-set bind: the feature gate
    binds identity, the probe binds surface, and together the executor
    serves exactly the FTDI common control surface the pinned grammar
    declares. An op no admitted kind can express refuses naming the op."""
    grammar = _grammar(pinned)
    executor = executor_for(pinned)
    assert executor is not None, "the feature gate admitted this pin"
    for op, payload in executor.probe_payloads.items():
        document = dict(payload)
        if not any(
            _first_schema_error(entry.request_validator, document) is None
            for entry in grammar.values()
        ):
            raise ValueError(
                f"live_provider_contract_unsupported: op {op!r} does not "
                "validate against the pinned contract's grammar; this "
                "executor serves the FTDI common control surface — pin the "
                "banked contract revision that declares it"
            )
    return grammar


@dataclass(frozen=True, slots=True)
class FtdiContract:
    """The verified served contract: the compiled grammar, the provider
    triple the services carry into the capture sidecar, and the contract's
    declared ``limits`` blocks (merged across grammar entries) — enforced
    at the ladder before any driver call (refute lane A, F3b: the schema
    alone admits set_baud 2**40; the limits block is the contract's own
    envelope and was previously enforced nowhere)."""

    grammar: dict[str, GrammarEntry]
    provider: dict[str, str]
    limits: dict[str, Any]
    ops: dict[str, tuple[str, ...]]
    byte_answer_ops: set[str] = field(default_factory=set)


def verify_ftdi_plugin(plugin: LoadedPlugin) -> FtdiContract:
    """The serve-construction check the CLI runs fail-fast and every
    connection re-runs over the CURRENT plugin (the late-bound
    ``replay_plugin_session`` shape: a reload that re-pins a different
    contract revision refuses the reconnect). Returns the verified
    contract — grammar, provider triple, limits. The CONTRACT checks run
    first and the deployment check (pyftdi present) last: a missing extra
    is a deployment error and must never mask a contract refusal at serve
    (refute lane A's ordering observation)."""
    pinned, digest = _ftdi_pinned_contract(plugin)
    _require_ftdi_feature(pinned, digest)
    grammar = _probe_grammar(pinned)
    _require_backend()
    provider = {
        "feature_id": str(pinned["feature_id"]),
        "id": str(pinned["id"]),
        "sha256": digest,
    }
    limits: dict[str, Any] = {}
    for entry in pinned["transaction_grammar"]:
        row = entry.get("limits")
        if isinstance(row, dict):
            limits.update(row)
    executor = executor_for(pinned)
    assert executor is not None, "the feature gate admitted this pin"
    return FtdiContract(
        grammar=grammar,
        provider=provider,
        limits=limits,
        ops=dict(executor.ops),
        byte_answer_ops=set(executor.byte_answer_ops),
    )


class _JournalState:
    """The session-scoped recorder state (refute lane A, F4): one journal
    accumulates across the session's connections — rows are never
    discarded on reconnect, the row names mark each connection boundary
    (``conn<n>-row<m>``), and every ``close_transport`` rewrites the
    ACCUMULATED document so even a mid-session close loses nothing."""

    def __init__(self, record_path: Any, provider: dict[str, str]) -> None:
        self.record_path = record_path
        self.provider = dict(provider)
        self.rows: list[dict[str, Any]] = []
        self.started_at: str
        self.connection = 0
        self.counter = 0

    def begin_connection(self) -> None:
        self.connection += 1
        if self.connection == 1:
            from datetime import UTC, datetime

            self.started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def name(self) -> str:
        self.counter += 1
        return f"conn{self.connection}-row{self.counter}"

    def document(self) -> dict[str, Any]:
        return {
            "journal_version": "1",
            "recorded": {
                "started_at": self.started_at,
                "source": "live_ftdi_session",
                "single_owner": True,
                "operator_note": (
                    f"{self.connection} connection(s); row names mark each "
                    "connection boundary"
                ),
            },
            "provider": dict(self.provider),
            "rows": self.rows,
        }


class RecordingFtdiCaptureServices(FtdiCaptureServices):
    """The live session's journal recorder (row b, the owner directive of
    2026-10-28): ``--record <path>`` emits a #564-format journal of what
    the device did, so a bench session produces replay evidence directly.

    The honesty rules (the recording never launders):

    - A COMPLETED exchange records its row: provider transactions in
      document form (bytes as the contract's base64 spelling), stream
      sends as hex frames (digest rows at the #564 bulk bound), receives
      with their bounds and their delivered frame — the quiet line
      ``b""`` records as the row's empty response, exactly as a recording
      of a quiet window should.
    - A receive whose deadline expired records
      ``recorded_failure: "timeout"`` and NO frame — the partial that
      stays buffered was never an outcome. Disclosed imprecision: a
      ``stream_exchange`` whose context expired before its write records
      the same timeout row (the row's request bytes replay as sent); the
      alternative — dropping post-send timeouts — would launder the
      common case, and the adapter driving a dead context is its own bug.
    - A REFUSED transaction records nothing: every ladder refusal
      (grammar, closed, busy, liveness, marker, unknown op) happens
      before dispatch, and a failed driver call has no journalable
      outcome — the rows are what the device did, never what it was
    asked. The overlong-line discard records nothing for the same reason
      (no representable outcome; the #564 format cannot carry it).

    The journal file writes at :meth:`close_transport` — the conversation
    is complete evidence once the session closes. A write failure warns
    and never blocks the device close (A07's posture: evidence storage is
    never a dependency of the close path).
    """

    def __init__(
        self,
        link: SerialLink,
        driver: FtdiDriver,
        grammar: dict[str, GrammarEntry],
        *,
        provider: dict[str, str],
        max_frame_bytes: int,
        capture_root: Any = None,
        capture_max_bytes: int | None = None,
        record_path: Any = None,
        limits: Mapping[str, Any] | None = None,
        journal: _JournalState | None = None,
        stream: FtdiStreamAdapter | None = None,
        ops: Mapping[str, tuple[str, ...]] | None = None,
        byte_answer_ops: Iterable[str] | None = None,
    ) -> None:
        super().__init__(
            link,
            driver,
            grammar,
            provider=provider,
            max_frame_bytes=max_frame_bytes,
            capture_root=capture_root,
            capture_max_bytes=capture_max_bytes,
            limits=limits,
            ops=ops,
            byte_answer_ops=byte_answer_ops,
        )
        # A shared state object carries the session's accumulation across
        # reconnects (F4); a bare record_path mints a private one (the
        # direct-construction unit arms).
        if journal is not None:
            self._journal = journal
        else:
            self._journal = _JournalState(record_path, provider)
        self._journal.begin_connection()
        self._stream = stream

    # -- row composition ------------------------------------------------------

    def _name(self) -> str:
        return self._journal.name()

    def _provider_row(self, transaction: dict[str, Any], result: dict[str, Any]) -> None:
        entry = self._grammar[transaction["kind"]]
        document = {
            key: (
                base64.b64encode(value).decode("ascii")
                if key in entry.request_b64 and isinstance(value, bytes)
                else value
            )
            for key, value in transaction.items()
            if key != "kind"
        }
        response = {
            key: (
                base64.b64encode(value).decode("ascii")
                if key in entry.result_b64 and isinstance(value, bytes)
                else value
            )
            for key, value in result.items()
        }
        self._journal.rows.append(
            {
                "name": self._name(),
                "transaction": dict(transaction, **document),
                "response": response,
            }
        )

    def _frame_fields(self, data: bytes) -> dict[str, Any]:
        """The send-side fields in the #564 spelling: inline hex below the
        bulk bound, the digest pair at or above it."""
        if len(data) >= BULK_INLINE_LIMIT:
            return {
                "data_sha256": hashlib.sha256(data).hexdigest(),
                "byte_length": len(data),
            }
        return {"data": data.hex()}

    def _bounds_fields(self, transaction: dict[str, Any]) -> dict[str, Any]:
        if "max_bytes" not in transaction:
            return {}
        return {
            "max_bytes": transaction["max_bytes"],
            "termination": transaction["termination"],
            "exact_bytes": transaction["exact_bytes"],
        }

    def _stream_row(self, transaction: dict[str, Any], result: dict[str, Any]) -> None:
        kind = transaction["kind"]
        fields: dict[str, Any] = {"kind": kind}
        if kind != "stream_receive":
            fields.update(self._frame_fields(transaction["data"]))
        fields.update(self._bounds_fields(transaction))
        response: dict[str, Any] = {}
        if kind != "stream_send" and result.get("data"):
            response = {"data": result["data"].hex()}
        self._journal.rows.append(
            {"name": self._name(), "transaction": fields, "response": response}
        )

    def _connection_failure_row(self, transaction: dict[str, Any]) -> None:
        """F5: the request went out in full; the connection then faulted.
        The row lands with ``recorded_failure: "connection"`` — a marker
        the #564 loader accepts and the replay host serves as the
        connection fault it was."""
        fields: dict[str, Any] = {"kind": transaction["kind"]}
        fields.update(self._frame_fields(transaction["data"]))
        fields.update(self._bounds_fields(transaction))
        self._journal.rows.append(
            {
                "name": self._name(),
                "transaction": fields,
                "recorded_failure": "connection",
            }
        )

    def _timeout_row(self, transaction: dict[str, Any]) -> None:
        kind = transaction["kind"]
        fields: dict[str, Any] = {"kind": kind}
        if kind != "stream_receive":
            fields.update(self._frame_fields(transaction["data"]))
        fields.update(self._bounds_fields(transaction))
        self._journal.rows.append(
            {
                "name": self._name(),
                "transaction": fields,
                "recorded_failure": "timeout",
            }
        )

    # -- the recording ladder ---------------------------------------------------

    async def transfer(
        self, transaction: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        kind = transaction.get("kind")
        if isinstance(kind, str) and kind in self._grammar:
            result = await super().transfer(transaction, context)
            self._provider_row(transaction, result)
            return result
        try:
            result = await super().transfer(transaction, context)
        except TimeoutError:
            # The receive-bearing kinds record the honest ambiguous
            # outcome; a pre-dispatch expiry on a send-only kind recorded
            # nothing (see the class docstring's disclosed imprecision).
            if isinstance(kind, str) and kind in ("stream_receive", "stream_exchange"):
                self._timeout_row(transaction)
            raise
        except ConnectionError:
            # F5 + F6 together: a fully-sent exchange whose receive
            # faulted lands its request row with the connection marker —
            # at least as honest as the timeout arm. The discriminator is
            # the ADAPTER's send-completion fact (``stream.completed``): a
            # failed, short or never-started send records nothing (it
            # never went out whole), and a receive-side fault after a full
            # send records the row. And the latch (F6): a faulted driver
            # (including a faulted link) stays faulted on this connection.
            if kind == "stream_exchange" and self._stream is not None and (
                self._stream.completed
            ):
                self._connection_failure_row(transaction)
            self._faulted = True
            raise
        self._stream_row(transaction, result)
        return result

    async def close_transport(self, context: Any) -> None:
        document = self._journal.document()
        try:
            self._journal.record_path.write_text(
                json.dumps(document, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
        except (OSError, ValueError) as exc:
            _LOGGER.warning(
                "live_provider_record_write: the journal was not written: %s", exc
            )
        await super().close_transport(context)


class FtdiEndpoint:
    """The ftdi session's endpoint source (row a, issue #568 — the
    SerialEndpoint posture one transport over): consulted AT CONNECT TIME
    by the services factory, so a rebind changes the next connection's
    URL. A bare string wraps as the constant resolver (the ``--device``
    form); a callable resolves from the binding store
    (:func:`benchweave_sdk_server.binding.binding_endpoint`)."""

    def __init__(self, source: str | Callable[[], str]) -> None:
        if callable(source):
            self._source = source
        else:
            url = str(source)
            self._source = lambda: url
        #: The URL the last successful open used; None until then.
        self.last_resolution: str | None = None

    def __call__(self) -> str:
        return self._source()


@dataclass(frozen=True)
class FtdiDeviceHooks:
    """The two device hooks ftdi discovery needs, injectable so tests
    never open real hardware (SerialPortHooks' posture, one transport
    over)."""

    enumerate_urls: Callable[[], list[str]]
    open_url: Callable[[str], FtdiDriver]


def _ftdi_scan_selectors() -> list[str]:
    """Enumerate every attached FTDI-class device the registered families
    cover, as canonical selectors (issue #589's enumeration replacement).

    pyftdi's product tables are never consulted — the scan is pyusb-level
    over the vendor ids the ``PROVIDER_EXECUTORS`` registry declares, so an
    OEM-rebranded pair lists exactly like an official one. ONE SELECTOR PER
    INTERFACE, ``1..ifcount``: a multi-port part (FT2232H, FT4232H) lists
    every port as an independently pickable selector and ``/1`` always
    means the first interface, which is the control port. The serial rides
    before the interface when the device reports one the selector charset
    can carry (a serial it cannot express is omitted, never mangled);
    rows sort for determinism. Every emitted selector is openable by the
    ladder (``open_ftdi``).
    """
    _ftdi_cls, _usbtools, usb_core, usb_util, _usbtools_error = _backend()
    try:
        rows: list[tuple[int, int, str | None, int]] = []
        for vendor in sorted(_registered_vendor_ids()):
            rows.extend(_scan_vendor_rows(usb_core, usb_util, vendor))
        # None-safe key INSIDE the guarded block: twins under one vid/pid
        # where one device reports no serial tuple-compare None against
        # str and would raise a bare TypeError past every typed refusal
        # (fold B) — an unsorted escape that made both devices invisible.
        rows.sort(key=lambda row: (row[0], row[1], row[2] or "", row[3]))
    except Exception as exc:
        raise RuntimeError(
            f"live_provider_enumeration_failed: {type(exc).__name__}: the "
            "FTDI family scan did not complete; scan again or pass "
            "--device <selector>"
        ) from exc
    selectors: list[str] = []
    for vid, pid, serial, ifcount in rows:
        serial_part = (
            f":{serial}"
            if serial is not None and _SERIAL_CHARS.match(serial)
            else ""
        )
        for port in range(1, ifcount + 1):
            selectors.append(
                f"ftdi://0x{vid:04x}:0x{pid:04x}{serial_part}/{port}"
            )
    return selectors


def default_ftdi_hooks() -> FtdiDeviceHooks:
    """The production hooks: the family vendor scan and the real open."""
    return FtdiDeviceHooks(enumerate_urls=_ftdi_scan_selectors, open_url=open_ftdi)


def _ftdi_device_row(
    plugin: LoadedPlugin,
    identity: dict[str, Any],
    *,
    url: str,
) -> dict[str, Any]:
    """One _DEVICE_SUMMARY row over an FTDI URL (the serial row's shape;
    the URL rides the port_path slot — the endpoint string slot, one row
    shape across transports)."""
    transport = plugin.descriptor.get("transport", {})
    return {
        "id": plugin.device_id,
        "manufacturer": str(identity.get("manufacturer", "")),
        "model": str(identity.get("model", "")),
        "transport": str(transport.get("type", "")),
        "connection_key": str(transport.get("connection_key", "")),
        "port_path": url,
        "usb_serial": None,
    }


async def discover_ftdi_devices(
    plugin: LoadedPlugin,
    *,
    hooks: FtdiDeviceHooks | None = None,
    connected_url: str | None = None,
    connected_identity: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Enumerate candidate FTDI URLs, confirm each by its identify answer,
    and return the confirmed devices as discovery rows (discover_serial_
    devices' posture, one transport over). The ONLY transmissions are the
    identify exchanges; the connected session's URL is served from its
    established identity without re-probing."""
    effective = hooks or default_ftdi_hooks()
    contract = verify_ftdi_plugin(plugin)
    rows: list[dict[str, Any]] = []
    for url in effective.enumerate_urls():
        if connected_url is not None and url == connected_url:
            if connected_identity is not None:
                rows.append(
                    _ftdi_device_row(plugin, connected_identity, url=url)
                )
            continue
        answered = await _confirm_ftdi_by_identify(
            plugin, url, effective, contract
        )
        if answered is None:
            continue
        rows.append(_ftdi_device_row(plugin, answered, url=url))
    return rows


async def _confirm_ftdi_by_identify(
    plugin: LoadedPlugin,
    url: str,
    hooks: FtdiDeviceHooks,
    contract: Any,
) -> dict[str, Any] | None:
    """Open one candidate URL and run the adapter's identify over a fresh
    services object: the ONLY transmission discovery performs. The
    answered identity must match the descriptor's declared manufacturer
    and model; a silent, erroring or foreign URL is omitted (an
    unconfirmed URL is not a device)."""
    from .session import HostOperationContext

    link: SerialLink | None = None
    adapter: Any = None
    try:
        driver = hooks.open_url(url)
        link = SerialLink(FtdiStreamAdapter(driver))
        services = FtdiCaptureServices(
            link,
            driver,
            contract.grammar,
            provider=contract.provider,
            max_frame_bytes=transport_ceiling(
                plugin.descriptor.get("transport", {}).get("settings", {})
            ),
            limits=contract.limits,
        )
        adapter = plugin.adapter_factory() if plugin.adapter_factory else None
        if adapter is None:
            return None
        context = HostOperationContext(
            f"discover-{uuid.uuid4().hex[:8]}", timeout_ms=_identify_timeout_ms(plugin)
        )
        await adapter.open(plugin.descriptor, services, context)
        envelope = await adapter.execute(
            {
                "operation_id": context.operation_id,
                "verb": "identify",
                "arguments": {},
            },
            context,
        )
        if envelope.get("status") != "ok":
            return None
        data = envelope.get("data")
        if not isinstance(data, dict):
            return None
        declared = plugin.descriptor.get("identity", {})
        if (
            data.get("manufacturer") != declared.get("manufacturer")
            or data.get("model") != declared.get("model")
        ):
            return None
        return data
    except ConformanceError as error:
        # The serial lane's FOLD-D arm, one transport over: an adapter
        # that transmits without a dispatch marker fails its own
        # conformance and the developer deserves to know why the device
        # did not appear — omitted, not silently. Silent, erroring and
        # foreign candidates stay unreported by design (AR-4: an
        # unconfirmed URL is not a device).
        _LOGGER.warning("ftdi discovery: %s omitted — %s", url, error)
        return None
    except Exception:
        # A silent, erroring or foreign candidate is omitted, not reported:
        # an unconfirmed URL is not a device (AR-4's posture).
        return None
    finally:
        if adapter is not None:
            with contextlib.suppress(Exception):
                close_context = HostOperationContext(
                    f"discover-close-{uuid.uuid4().hex[:8]}",
                    timeout_ms=_identify_timeout_ms(plugin),
                )
                await adapter.close(close_context)
        if link is not None:
            with contextlib.suppress(Exception):
                link.close()


def ftdi_plugin_session(
    plugin: LoadedPlugin,
    url: str | FtdiEndpoint | Callable[[], str],
    *,
    driver_factory: Any = None,
    capture_root: Any = None,
    capture_max_bytes: int | None = None,
    record_path: Any = None,
) -> PluginSession:
    """A ``PluginSession`` over the live FTDI provider transport: each
    connection re-verifies the CURRENT plugin's pin, feature and grammar
    (a reload that unpins or re-pins refuses the reconnect, never serves a
    conversation against a contract it was not admitted on) and opens the
    device per connection — a fresh conversation over a fresh driver and
    link (the M1 fold's per-connection law). ``driver_factory`` is the
    injection axis for tests (the ``open_port`` precedent); production
    uses :func:`open_ftdi` and its one bounded open attempt.
    ``record_path`` arms the live journal recorder (row b): the session's
    exchanges emit a #564-format journal at close."""
    open_driver = driver_factory or open_ftdi
    # The endpoint (row a): a bare URL wraps as the constant resolver; an
    # FtdiEndpoint or callable resolves AT CONNECT TIME (the serial lane's
    # late-bound shape — a rebind redirects the next connection).
    resolve_url: Callable[[], str] = (
        url if callable(url) and not isinstance(url, str) else (lambda: str(url))
    )
    journal = _JournalState(record_path, {}) if record_path is not None else None

    def factory() -> FtdiCaptureServices:
        contract = verify_ftdi_plugin(session.plugin)
        # A3 (the mechanism refute): resolve the endpoint ONCE — the
        # driver opens the URL this call returns and last_resolution
        # records the SAME value. The double call was an executed desync
        # (a mutable endpoint served a different URL to each).
        resolved_url = resolve_url()
        driver = open_driver(resolved_url)
        settings = session.plugin.descriptor.get("transport", {}).get("settings", {})
        if isinstance(url, FtdiEndpoint):
            url.last_resolution = resolved_url
        stream = FtdiStreamAdapter(driver)
        link = SerialLink(stream)
        common: dict[str, Any] = {
            "provider": contract.provider,
            "max_frame_bytes": transport_ceiling(settings),
            "capture_root": capture_root,
            "capture_max_bytes": capture_max_bytes,
            "limits": contract.limits,
            "ops": contract.ops,
            "byte_answer_ops": contract.byte_answer_ops,
        }
        services: FtdiCaptureServices
        if journal is None:
            services = FtdiCaptureServices(link, driver, contract.grammar, **common)
        else:
            # The session's journal state carries the provider triple the
            # document names (the CURRENT plugin's verified pin).
            journal.provider = contract.provider
            services = RecordingFtdiCaptureServices(
                link, driver, contract.grammar, journal=journal,
                stream=stream, **common
            )
        return services

    session: PluginSession = PluginSession(plugin, factory)
    # The rehearsal marker (the acceptance review's A): a session over an
    # INJECTED driver factory runs the shipped scripted double, and every
    # surface that speaks "ftdi" must disclose it. The CLI never injects
    # (production is always live); embedded hosts and generated test
    # suites do, and they must not read as hardware.
    session.rehearsal = driver_factory is not None
    return session
