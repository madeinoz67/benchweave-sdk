"""The device-generic FTDI selector ladder and enumeration (issue #589, PR-1).

The fake backend here is the TABLE-GATE MINIATURE: pyftdi 0.57.2's URL
machinery searches only the static ``Ftdi.PRODUCT_IDS`` table, so an OEM
product id is URL-inadmissible while ``find_all``/``open`` over the concrete
pair work — the issue in miniature, no hardware. Every arm drives the
production ladder (:func:`benchweave_sdk_server.ftdi.open_ftdi`) with the
backend seam injected; nothing opens a real bus.

Invented identifiers throughout: vendor ``0x0403`` is FTDI's own vendor id
(the family registration's, and the class the user guide prints);
``0xd1a4`` is an invented OEM product id; ``0x6001``/``0x6010`` are FTDI's
official product ids (the table miniature needs official rows); ``610042``
and every other serial here are invented. No real device, plugin or bench
is named.

The live arms (marker ``live_ftdi``) run only on a bench with an FTDI-class
device attached; CI deselects the marker and the arms also skip themselves
when no device answers.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk_server import ftdi as ftdi_module
from benchweave_sdk_server.ftdi import open_ftdi
from benchweave_sdk_server.session import load_plugin_project

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "ftdi_control_plugin"

#: The miniature's official table (the class of row pyftdi's PRODUCT_IDS
#: carries) and the vendor-name map its URL parse needs.
_OFFICIAL_TABLE: dict[int, dict[str, int]] = {
    0x0403: {"232": 0x6001, "2232h": 0x6010},
}
_VENDOR_NAMES: dict[str, int] = {"ftdi": 0x0403}

_OFFICIAL_PID = 0x6001
_OEM_PID = 0xD1A4  # invented OEM product id — absent from the official table
_MULTI_PID = 0x6010  # official; the miniature's multi-interface device shape


class FakeUsbToolsError(Exception):
    """The miniature of pyftdi's ``UsbToolsError``: the resolution-class
    failure (parse, table gate, no match, ambiguity) — the only class the
    ladder's fallback is gated on."""


class FakeUSBError(Exception):
    """The miniature of pyusb's ``USBError``: a claim-time failure (busy,
    permission) that must NOT trigger the fallback — one bounded attempt."""


class FakeFtdiError(Exception):
    """The miniature of pyftdi's ``FtdiError``: pyftdi's own FTDI-level
    failure — the LATE interface guard (``No such FTDI port: N``, raised in
    ``open_from_device`` AFTER the device is resolved and before the claim)
    and the pre-claim URL-path refusals. Claim/busy/permission arrive from
    pyusb as ``USBError`` instead, never wrapped in this class."""


class FakeDescriptor:
    """The ``UsbDeviceDescriptor`` fields the ladder reads: vid, pid, sn."""

    def __init__(self, vid: int, pid: int, sn: str | None) -> None:
        self.vid = vid
        self.pid = pid
        self.sn = sn


def _pyftdi_to_int(text: str) -> int | None:
    """``pyftdi.misc.to_int`` mirrored from the installed wheel (misc.py's
    ``to_int``): the decimal branch — digits plus an optional K/M unit
    suffix — and the lowercase-``0x`` hex branch. ``None`` when pyftdi
    would treat the text as a non-number (a serial string). The FAKE needs
    the full mirror because pyftdi's index reading is what fold A trapped:
    a third netloc component whose value parses <= 255 selects
    ``candidates[n]`` (usbtools.py's enumerate_candidates), never a
    serial."""
    mo = re.match(r"\A\s*(\d+)\s*(?:([KMkm]i?)?B?)?\s*\Z", text)
    if mo:
        value = int(mo.group(1))
        if mo.group(2):
            value *= {
                "K": 1000,
                "KI": 1 << 10,
                "M": 1000 * 1000,
                "MI": 1 << 20,
            }[mo.group(2).upper()]
        return value
    if text.startswith("0x"):
        try:
            return int(text, 16)
        except ValueError:
            return None
    return None


class FakeOpenedDevice:
    """What pyftdi's ``Ftdi._usb_dev`` looks like after an open: the pyusb
    device, of which the ladder reads exactly ``serial_number``."""

    def __init__(self, serial: str | None) -> None:
        self.serial_number = serial


class FakeUsbTools:
    """The ``UsbTools`` miniature: a mutable device inventory and the
    per-pair cache pyftdi keeps until a flush — the staleness miniature the
    ``nocache=True`` resolution must bypass, with every call's flag
    recorded."""

    def __init__(self, devices: list[tuple[FakeDescriptor, int]]) -> None:
        self.devices = list(devices)
        self.find_all_calls: list[tuple[int, int | None]] = []
        self.nocache_flags: list[bool] = []
        self._cache: dict[tuple[int, int], list[tuple[FakeDescriptor, int]]] = {}

    def find_all(
        self, vps: list[tuple[int, int | None]], nocache: bool = False
    ) -> list[tuple[FakeDescriptor, int]]:
        self.find_all_calls.extend(vps)
        self.nocache_flags.append(nocache)
        out: list[tuple[FakeDescriptor, int]] = []
        for vid, pid in vps:
            key = (vid, pid)
            if nocache or key not in self._cache:
                self._cache[key] = [
                    (d, c) for (d, c) in self.devices if d.vid == vid and d.pid == pid
                ]
            out.extend(self._cache[key])
        return out


class FakeConfig:
    def __init__(self, ifcount: int) -> None:
        self.bNumInterfaces = ifcount


class FakeUsbDevice:
    """A pyusb device miniature for the vendor scan: iterated for its
    configurations, read for ids and the serial string index."""

    def __init__(self, vid: int, pid: int, serial: str | None, ifcount: int) -> None:
        self.idVendor = vid
        self.idProduct = pid
        self.serial = serial
        self.iSerialNumber = 1 if serial else 0
        self._configs = [FakeConfig(ifcount)]

    def __iter__(self) -> Iterator[FakeConfig]:
        return iter(self._configs)


class FakeUsbCore:
    """The ``usb.core`` miniature: ``find(find_all=True, idVendor=...)`` over
    the same inventory the fake UsbTools serves (pyusb-level, table-free)."""

    def __init__(self, devices: list[FakeUsbDevice]) -> None:
        self.devices = list(devices)
        self.finds: list[int | None] = []

    def find(self, find_all: bool = False, idVendor: int | None = None) -> list[Any]:
        self.finds.append(idVendor)
        return [d for d in self.devices if d.idVendor == idVendor]


class FakeUsbUtil:
    """The ``usb.util`` miniature: the serial-string reader."""

    def __init__(self) -> None:
        self.calls = 0

    def get_string(self, dev: Any, index: int) -> str | None:
        self.calls += 1
        return dev.serial if index else None


#: The staged world, shared by both fake inventories. Arms restage it.
_INVENTORY: list[tuple[FakeDescriptor, int]] = []
_USB_DEVICES: list[FakeUsbDevice] = []
_INSTANCES: list[FakeFtdi] = []


class FakeFtdi:
    """The ``Ftdi`` miniature: the static PRODUCT_IDS table (the gate the
    design's root cause named), ``add_custom_product`` with pyftdi's exact
    already-registered ``ValueError`` and in-place table mutation, the
    joker-URL ``list_devices`` enumeration the containment arm asserts
    against, and the two open paths recording what the ladder did."""

    PRODUCT_IDS: dict[int, dict[str, int]] = {}
    #: The real class carries the BitMode enum the driver coerces through;
    #: int stands in for the fake (the ladder never dispatches a transaction
    #: in these arms).
    BitMode = int
    #: An optional forced failure for ``open`` (the claim-failure arm).
    fail_open_with: BaseException | None = None

    def __init__(self) -> None:
        self.usb_dev: Any = None
        self.closed = 0
        self.open_calls: list[dict[str, Any]] = []
        self.url_calls: list[str] = []
        #: The table's product ids AT EACH open_from_url call — where the
        #: transient registration is observable (rev 7 §2.2: registered
        #: during the attempt, restored after it).
        self.table_pids_at_open: list[set[int]] = []
        _INSTANCES.append(self)

    @classmethod
    def reset_table(cls) -> None:
        cls.PRODUCT_IDS = {vid: dict(rows) for vid, rows in _OFFICIAL_TABLE.items()}
        cls.fail_open_with = None

    @classmethod
    def add_custom_product(cls, vid: int, pid: int, pidname: str = "") -> None:
        # pyftdi 0.57.2's body, mirrored: insert-only, class-level, in-place
        # mutation of the per-vid row, ValueError on a re-registration.
        if vid not in cls.PRODUCT_IDS:
            cls.PRODUCT_IDS[vid] = {}
        elif pid in cls.PRODUCT_IDS[vid].values():
            raise ValueError(f"Product ID 0x{vid:04x}:0x{pid:04x} already registered")
        if not pidname:
            pidname = f"0x{pid:04x}"
        cls.PRODUCT_IDS[vid][pidname] = pid

    @classmethod
    def list_devices(cls, url: str | None = None) -> list[tuple[FakeDescriptor, int]]:
        """The joker-URL enumeration miniature: every staged device the
        CURRENT table admits — the lens that sees a leaked registration."""
        return [
            (d, c)
            for (d, c) in _INVENTORY
            if d.pid in cls.PRODUCT_IDS.get(d.vid, {}).values()
        ]

    # -- the miniature URL parse: vendor names then hex components, the
    # product component gated on the table exactly as pyftdi gates it --
    def open_from_url(self, url: str) -> None:
        self.url_calls.append(url)
        body = url.split("://", 1)[1]
        netloc, _, path = body.partition("/")
        components = netloc.split(":")
        self.table_pids_at_open.append(
            set(self.PRODUCT_IDS.get(_table_vid(components), {}).values())
        )
        try:
            vendor = components[0]
            if vendor in _VENDOR_NAMES:
                vid = _VENDOR_NAMES[vendor]
            elif vendor:
                vid = int(vendor, 16)
            else:
                vid = 0
            pid: int | None = None
            if len(components) > 1 and components[1]:
                table = self.PRODUCT_IDS.get(vid, {})
                pid = (
                    table[components[1]]
                    if components[1] in table
                    else int(components[1], 16)
                )
            if path and not path.isdigit():
                raise FakeUsbToolsError(f"Invalid device URL: {url}")
        except ValueError as exc:
            raise FakeUsbToolsError(f"Invalid device URL: {url}") from exc
        if pid is None or pid not in self.PRODUCT_IDS.get(vid, {}).values():
            raise FakeUsbToolsError(f"No USB device matches URL {url}")
        # pyftdi's LOCATOR semantics (usbtools.enumerate_candidates), the
        # behaviour fold A trapped: a third component whose to_int value is
        # <= 255 is a 0-BASED INDEX into the candidates; only a component
        # to_int cannot read (or reads > 255) is a serial string. The
        # serial-semantics model this fake carried before is exactly what
        # hid the wrong-device open.
        candidates = [d for d, _ in _INVENTORY if d.vid == vid and d.pid == pid]
        if len(components) > 2 and components[2]:
            value = _pyftdi_to_int(components[2])
            if value is not None and value <= 255:
                try:
                    matched = candidates[value - 1 if value else 0]
                except IndexError:
                    raise FakeUsbToolsError(
                        f"No USB device matches URL {url}"
                    ) from None
            else:
                serial_matches = [d for d in candidates if d.sn == components[2]]
                if len(serial_matches) > 1:
                    raise FakeUsbToolsError(
                        f"{len(serial_matches)} USB devices match URL {url}"
                    )
                if not serial_matches:
                    raise FakeUsbToolsError(
                        f"No USB device with S/N {components[2]}"
                    )
                matched = serial_matches[0]
        else:
            if len(candidates) > 1:
                raise FakeUsbToolsError(f"{len(candidates)} USB devices match URL {url}")
            if not candidates:
                raise FakeUsbToolsError(f"No USB device matches URL {url}")
            matched = candidates[0]
        # pyftdi's LATE interface guard (ftdi.py's open_from_device): the
        # interface argument is checked against the resolved device's own
        # interface count AFTER resolution, raising FtdiError — the failure
        # fold C routes to the ladder's typed range check.
        ifcount = next(c for d, c in _INVENTORY if d is matched)
        port = int(path) if path else 1
        if port > ifcount:
            raise FakeFtdiError(f"No such FTDI port: {port}")
        self._usb_dev = FakeOpenedDevice(matched.sn)

    def open(
        self, vid: int, pid: int, serial: str | None = None, interface: int = 1
    ) -> None:
        self.open_calls.append(
            {"vid": vid, "pid": pid, "serial": serial, "interface": interface}
        )
        if FakeFtdi.fail_open_with is not None:
            raise FakeFtdi.fail_open_with
        matches = [
            d
            for d, _ in _INVENTORY
            if d.vid == vid and d.pid == pid and (serial is None or d.sn == serial)
        ]
        if not matches:
            raise OSError("Device not found")
        self._usb_dev = FakeOpenedDevice(matches[0].sn)

    def close(self) -> None:
        self.closed += 1


def _table_vid(components: list[str]) -> int:
    """The vid row the table snapshot keys on (the named-vendor map first,
    bare hex second — the miniature URL parse's own rule)."""
    vendor = components[0] if components else ""
    if vendor in _VENDOR_NAMES:
        return _VENDOR_NAMES[vendor]
    try:
        return int(vendor, 16) if vendor else 0
    except ValueError:
        return 0


def _install_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    devices: list[tuple[tuple[int, int, str | None], int]] | None = None,
) -> tuple[FakeUsbTools, FakeUsbCore]:
    """Stage the fake world (both inventories) and inject the backend seam.
    ``devices`` rows are ((vid, pid, serial), interface_count)."""
    FakeFtdi.reset_table()
    _INVENTORY.clear()
    _USB_DEVICES.clear()
    _INSTANCES.clear()
    for (vid, pid, sn), ifcount in devices or []:
        _INVENTORY.append((FakeDescriptor(vid, pid, sn), ifcount))
        _USB_DEVICES.append(FakeUsbDevice(vid, pid, sn, ifcount))
    usbtools = FakeUsbTools(_INVENTORY)
    core = FakeUsbCore(_USB_DEVICES)
    monkeypatch.setattr(
        ftdi_module,
        "_BACKEND",
        lambda: (FakeFtdi, usbtools, core, FakeUsbUtil(), FakeUsbToolsError, FakeFtdiError),
    )
    return usbtools, core


@pytest.fixture(autouse=True)
def _fresh_world() -> Iterator[None]:
    yield
    FakeFtdi.reset_table()
    FakeFtdi.fail_open_with = None
    _INVENTORY.clear()
    _USB_DEVICES.clear()
    _INSTANCES.clear()


@pytest.fixture(scope="module")
def plugin():
    return load_plugin_project(FIXTURE_ROOT)


# ---------------------------------------------------------------------------
# The selector grammar (rev 7: one separator, one interface spelling)
# ---------------------------------------------------------------------------

Parsed = tuple[int | None, int | None, str | None, int, bool]


def _parsed(text: str) -> Parsed:
    selector = ftdi_module._parse_ftdi_selector(text)
    return (selector.vid, selector.pid, selector.serial, selector.port, selector.url_form)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The colon form: colon is the VID/PID separator, /N the ONLY
        # interface spelling, the serial the third colon component.
        ("0403:d1a4", (0x0403, 0xD1A4, None, 1, False)),
        ("0x0403:0xd1a4", (0x0403, 0xD1A4, None, 1, False)),
        ("0403:d1a4/2", (0x0403, 0xD1A4, None, 2, False)),
        ("0403:d1a4:610042", (0x0403, 0xD1A4, "610042", 1, False)),
        ("0403:d1a4:610042/2", (0x0403, 0xD1A4, "610042", 2, False)),
        # A numeric serial is a serial, carried VERBATIM (rev 7 §2.2) — the
        # round-trip arm below opens by it.
        ("0403:6001:7", (0x0403, 0x6001, "7", 1, False)),
        # A bare VID admits any product under it (resolved through the
        # registered-vendor scan) — the record's bare form carries no
        # interface suffix (qualify with a pid to pick a port).
        ("0403", (0x0403, None, None, 1, False)),
        # The URL form reduces to a pair only when every netloc component is
        # expressible in the colon grammar; anything else passes through
        # opaque (the incumbent path's own vocabulary).
        ("ftdi://0x0403:0x6001/1", (0x0403, 0x6001, None, 1, True)),
        ("ftdi://0403:6001/1", (0x0403, 0x6001, None, 1, True)),
        ("ftdi://0x0403:0x6001:610042/2", (0x0403, 0x6001, "610042", 2, True)),
        ("ftdi://0x0403:0x6001:A1/1", (0x0403, 0x6001, "A1", 1, True)),
        ("ftdi://0x0403/1", (0x0403, None, None, 1, True)),
        ("ftdi://0x0403:0x6001", (0x0403, 0x6001, None, 1, True)),
        ("ftdi://ftdi:232:610042/1", (None, None, None, 1, True)),
        # The never-matching bus/address shape does NOT reduce to a pair
        # (the corrected docstring example: pyftdi reads it as bus/address,
        # so the ladder must not promise a fallback for it).
        ("ftdi://::0x0403:0x6001/1", (None, None, None, 1, True)),
    ],
)
def test_the_selector_grammar_parses_each_form_once(text: str, expected: Parsed) -> None:
    assert _parsed(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not-a-selector",
        "0403:",
        ":0403",
        "0403:zzzz",
        "0403:d1a4:",
        "0403:d1a4:610042:extra",
        # The separator is colon ONLY: '/' as a VID/PID separator made
        # '0403/dc48/2' two-parse (rev 7 fold 5) — it is malformed now.
        "0403/d1a4",
        "0403/d1a4/2",
        # '@N' is dropped: one concept, one spelling.
        "0403:d1a4@2",
        "0403@2",
        "0403:d1a4@",
        # The bare-VID form carries no interface suffix (the record's
        # grammar); a port choice needs the qualified pair.
        "0403/2",
        # The interface suffix is 1-2 digits.
        "0403:d1a4/123",
        # The serial charset carries no separator of its own.
        "0403:d1a4:bad!serial",
        "0403:d1a4:" + "x" * 65,
        # pyftdi's '?' listing form would SystemExit a host; a non-index
        # interface path is refused at this boundary.
        "ftdi://0x0403:0x6001/?",
        "ftdi://0x0403:0x6001/abc",
        "ftdi://0x0403:0x6001/123",
    ],
)
def test_an_unparseable_selector_refuses_typed(text: str) -> None:
    """Rev 7 fold 7d: malformed input is its own refusal —
    ``live_provider_selector_malformed:`` naming the input and the accepted
    forms — never ``live_provider_device_unavailable:`` (that prefix means
    an absent or unopenable device; a typo is neither)."""
    with pytest.raises(
        RuntimeError, match="live_provider_selector_malformed:"
    ) as excinfo:
        ftdi_module._parse_ftdi_selector(text)
    assert repr(text.strip()) in str(excinfo.value) or text in str(excinfo.value)


@pytest.mark.parametrize("text", ["0403:d1a4/0", "ftdi://0x0403:0x6001/0"])
def test_port_zero_refuses_with_the_range_named(text: str) -> None:
    """pyftdi silently coerces ``/0`` to 1; this boundary refuses 0
    explicitly (``live_provider_interface_out_of_range:``), naming that the
    interface index is 1-based."""
    with pytest.raises(RuntimeError, match="live_provider_interface_out_of_range:"):
        ftdi_module._parse_ftdi_selector(text)


# ---------------------------------------------------------------------------
# The ladder: the table-gate miniature, the fallback, the one-attempt law
# ---------------------------------------------------------------------------


def test_the_oem_pair_resolves_through_the_enumerated_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issue in miniature: the OEM product id is absent from the table
    (``open_from_url``'s gate), the colon-form selector resolves through
    ``find_all`` over the concrete pair and a direct ``open`` — the pair the
    live bench proved table-free. ``nocache=True`` rides every enumeration
    (the bus as it is now)."""
    usbtools, _core = _install_backend(monkeypatch, devices=[((0x0403, _OEM_PID, None), 1)])
    driver = open_ftdi("0403:d1a4")
    assert isinstance(driver, ftdi_module._PyftdiDriver)
    assert usbtools.find_all_calls == [(0x0403, _OEM_PID)]
    assert usbtools.nocache_flags == [True]
    assert _INSTANCES[-1].open_calls == [
        {"vid": 0x0403, "pid": _OEM_PID, "serial": None, "interface": 1}
    ]


def test_find_all_never_receives_a_none_product_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The permanent machine guard: ``find_all([(vid, None)])`` is
    structurally empty on pyftdi 0.57.2 (the vendor filter excludes every
    real product id), so the ladder must never issue a pair with a None
    product id — asserted over the recorded calls of every resolve this arm
    drives, the bare-VID path included (it enumerates the vendor scan
    instead). What the guard does not catch: a resolution path that never
    calls ``find_all`` at all."""
    usbtools, _core = _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OEM_PID, None), 1),
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
        ],
    )
    open_ftdi("0403:d1a4")
    # The bare-VID path resolves through the vendor scan — two devices under
    # the vendor refuse ambiguity (never first-match-wins), and neither path
    # ever hands find_all a None product id.
    with pytest.raises(RuntimeError, match="live_provider_device_ambiguous:"):
        open_ftdi("0403")
    assert usbtools.find_all_calls, "the ladder resolved nothing"
    assert all(pid is not None for _, pid in usbtools.find_all_calls)


# -- the contained add_custom_product: registered during, restored after --


def test_the_url_form_registers_the_selectors_own_pair_during_the_attempt_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rev 7 §2.2/R4: the URL-form passthrough registers the operator's OWN
    parsed pair immediately before ``open_from_url`` so the OEM URL form
    opens through the incumbent path — and the save/restore ``finally``
    removes it again, because pyftdi 0.57.2 is insert-only at class level
    and a leaked row makes a LATER joker-URL enumeration see the pair. The
    registration is observable only DURING the attempt (the table snapshot
    each ``open_from_url`` call records); after the resolve the class table
    and the joker enumeration are clean."""
    usbtools, _core = _install_backend(monkeypatch, devices=[((0x0403, _OEM_PID, None), 1)])
    driver = open_ftdi("ftdi://0x0403:0xd1a4/1")
    assert isinstance(driver, ftdi_module._PyftdiDriver)
    # During the attempt the table carried the selector's own pair …
    assert _INSTANCES[-1].url_calls == ["ftdi://0x0403:0xd1a4/1"]
    assert _OEM_PID in _INSTANCES[-1].table_pids_at_open[0]
    assert _INSTANCES[-1].open_calls == []  # the URL attempt is the one that opened
    assert usbtools.find_all_calls == []  # no fallback was needed
    # … and after the resolve it does not: restore, not merge.
    assert _OEM_PID not in FakeFtdi.PRODUCT_IDS[0x0403].values()
    leaked = [d for d, _ in FakeFtdi.list_devices("ftdi:///1") if d.pid == _OEM_PID]
    assert leaked == [], "a joker-URL enumeration still sees the OEM pair"


def test_a_second_resolve_of_the_same_oem_url_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reconnect trap, both halves: re-registering the same pair raises
    pyftdi's ValueError (defused by the membership guard), and the restore
    must not cost the feature it protects — two consecutive resolves of the
    same OEM URL selector both open."""
    _install_backend(monkeypatch, devices=[((0x0403, _OEM_PID, None), 1)])
    assert isinstance(
        open_ftdi("ftdi://0x0403:0xd1a4/1"), ftdi_module._PyftdiDriver
    )
    assert isinstance(
        open_ftdi("ftdi://0x0403:0xd1a4/1"), ftdi_module._PyftdiDriver
    )
    # Each resolve is a fresh instance attempting the URL once (the
    # membership guard defused the re-registration trap both times).
    url = "ftdi://0x0403:0xd1a4/1"
    assert [instance.url_calls for instance in _INSTANCES] == [[url], [url]]


def test_a_failed_url_attempt_restores_the_table_and_discloses_the_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the URL attempt still fails after a transient registration, the
    refusal DISCLOSES the registration (rev 7 §2.2) and the table is clean
    again whether the fallback refuses or never runs."""
    _install_backend(monkeypatch, devices=[])
    with pytest.raises(
        RuntimeError, match="live_provider_device_unavailable:"
    ) as excinfo:
        open_ftdi("ftdi://0x0403:0xd1a4/1")
    assert "registered for the URL attempt and removed again" in str(excinfo.value)
    assert _OEM_PID not in FakeFtdi.PRODUCT_IDS.get(0x0403, {}).values()


# -- the fallback's contract --


def test_the_numeric_serial_round_trips_into_the_fallback_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The round-trip arm: this device class reports NUMERIC serials. A
    twin pair under one vid/pid resolves by the numeric serial — the direct
    ``open`` receives the SAME serial the selector carried (the fallback
    reuses the selector's own parse; it never drops a serial to widen the
    match)."""
    _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
            ((0x0403, _OFFICIAL_PID, "700001"), 1),
        ],
    )
    driver = open_ftdi("0403:6001:610042")
    assert isinstance(driver, ftdi_module._PyftdiDriver)
    assert _INSTANCES[-1].open_calls == [
        {"vid": 0x0403, "pid": _OFFICIAL_PID, "serial": "610042", "interface": 1}
    ]


def test_twins_without_a_serial_refuse_ambiguity_listing_every_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never first-match-wins: two devices under one vid/pid with no serial
    in the selector refuse ``live_provider_device_ambiguous:`` naming the
    count and every candidate ``vid:pid:serial``, so the operator picks
    (pyftdi's own URL ambiguity error is the same class of event; the
    fallback confirms it by enumeration)."""
    usbtools, _core = _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
            ((0x0403, _OFFICIAL_PID, "700001"), 1),
        ],
    )
    with pytest.raises(RuntimeError, match="live_provider_device_ambiguous:") as excinfo:
        open_ftdi("0403:6001")
    message = str(excinfo.value)
    assert "2" in message
    assert "0x0403:0x6001:610042" in message
    assert "0x0403:0x6001:700001" in message
    assert usbtools.find_all_calls  # the enumeration confirmed the ambiguity


def test_a_serial_the_url_attempt_refused_is_never_dropped_by_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal-consistency arm: the URL attempt refuses a serial that
    matches no device; the fallback reuses the SAME parsed serial and
    therefore also finds zero — it can never open a sibling the URL
    deliberately refused."""
    _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
            ((0x0403, _OFFICIAL_PID, "700001"), 1),
        ],
    )
    with pytest.raises(
        RuntimeError, match="live_provider_device_unavailable:"
    ) as excinfo:
        open_ftdi("ftdi://0x0403:0x6001:800001/1")
    assert "enumeration found 0 matching device(s)" in str(excinfo.value)
    assert _INSTANCES[-1].open_calls == []  # nothing was opened on the siblings


def test_a_claim_failure_never_triggers_a_second_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy or permission-refused device (a CLAIM failure, not a
    resolution failure) refuses immediately — ``find_all`` is never reached,
    exactly one open attempt, the handle closed (the retry the one-attempt
    law forbids is the one a broad ``except`` would smuggle in)."""
    usbtools, _core = _install_backend(
        monkeypatch, devices=[((0x0403, _OFFICIAL_PID, "610042"), 1)]
    )

    def _busy_url(self: FakeFtdi, url: str) -> None:
        raise FakeUSBError("Resource busy")

    monkeypatch.setattr(FakeFtdi, "open_from_url", _busy_url)
    with pytest.raises(RuntimeError, match="live_provider_device_unavailable:"):
        open_ftdi("ftdi://0x0403:0x6001/1")
    assert usbtools.find_all_calls == []  # no enumeration, no second claim
    assert _INSTANCES[-1].closed == 1  # the handle closed


def test_a_failed_fallback_open_closes_the_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pyftdi sets its USB device before a claim can fail, so a failed
    ``open`` on the fallback path closes the handle before the refusal —
    the incumbent's close-on-failure, kept."""
    _install_backend(monkeypatch, devices=[((0x0403, _OEM_PID, None), 1)])
    FakeFtdi.fail_open_with = FakeUSBError("Resource busy")
    try:
        with pytest.raises(RuntimeError, match="live_provider_device_unavailable:"):
            open_ftdi("0403:d1a4")
    finally:
        FakeFtdi.fail_open_with = None
    assert _INSTANCES[-1].closed == 1


def test_zero_matches_names_the_selector_and_the_url_error_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a device-less machine the ladder answers
    ``live_provider_device_unavailable:`` naming the selector, the URL
    attempt's exception class when there was one, and "enumeration found 0
    matching device(s)" — strictly more diagnostic than the bare class."""
    _install_backend(monkeypatch, devices=[])
    with pytest.raises(
        RuntimeError, match="live_provider_device_unavailable:"
    ) as excinfo:
        open_ftdi("0403:d1a4")
    assert "0403:d1a4" in str(excinfo.value)
    assert "enumeration found 0 matching device(s)" in str(excinfo.value)
    with pytest.raises(
        RuntimeError, match="live_provider_device_unavailable:"
    ) as url_excinfo:
        open_ftdi("ftdi://0x0403:0x6001/1")
    assert "FakeUsbToolsError" in str(url_excinfo.value)


def test_an_opaque_url_form_still_opens_through_the_incumbent_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A URL spelling the colon grammar cannot reduce to a numeric pair (a
    named vendor) still passes through ``open_from_url`` unchanged — the
    incumbent path is preserved for every spelling that ever worked; the
    fallback simply has no pair to enumerate for it."""
    usbtools, _core = _install_backend(
        monkeypatch, devices=[((0x0403, _OFFICIAL_PID, "610042"), 1)]
    )
    driver = open_ftdi("ftdi://ftdi:232:610042/1")
    assert isinstance(driver, ftdi_module._PyftdiDriver)
    assert usbtools.find_all_calls == []
    assert _INSTANCES[-1].url_calls == ["ftdi://ftdi:232:610042/1"]


def test_a_bare_vid_admits_any_product_under_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare-VID selector resolves through the same registered-vendor scan
    the enumeration uses — any product under the vendor, one device opens,
    twins without a serial refuse ambiguity (never first-match-wins over
    pyftdi's set-ordered device list)."""
    _install_backend(monkeypatch, devices=[((0x0403, _OEM_PID, None), 1)])
    driver = open_ftdi("0403")
    assert isinstance(driver, ftdi_module._PyftdiDriver)
    assert _INSTANCES[-1].open_calls[0]["pid"] == _OEM_PID

    _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OEM_PID, None), 1),
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
        ],
    )
    with pytest.raises(RuntimeError, match="live_provider_device_ambiguous:"):
        open_ftdi("0403")


def test_a_bare_vid_on_an_unregistered_vendor_refuses_zero_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boundary sentence, exact for the bare-VID form too: auto-discovery
    is family-scoped, so a bare VID naming a vendor no executor registers
    refuses "0 matching" and directs the operator to qualify it with a pid —
    the family registry is the anti-laundering gate, not a per-device
    special case."""
    _install_backend(monkeypatch, devices=[((0x1F71, 0x0111, "B2"), 1)])
    with pytest.raises(
        RuntimeError, match="live_provider_device_unavailable:"
    ) as excinfo:
        open_ftdi("1f71")
    assert "enumeration found 0 matching device(s)" in str(excinfo.value)
    assert "pid" in str(excinfo.value)
    assert _INSTANCES[-1].open_calls == []


# ---------------------------------------------------------------------------
# Interface range, cache staleness, seam typing
# ---------------------------------------------------------------------------


def test_the_same_bad_port_refuses_identically_from_both_forms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fold C (refute lane 1): one input, two spellings, ONE refusal — port
    2 on a 1-interface device is ``live_provider_interface_out_of_range:``
    naming ``1..1`` whether the selector spells it ``0403:6001/2`` or
    ``ftdi://0x0403:0x6001/2``. The URL arm used to answer
    ``device_unavailable`` ("URL attempt: FtdiError") because pyftdi's LATE
    interface guard fired after resolution and the ladder surfaced the raw
    class — two causes for one operator mistake. The URL arm's FtdiError is
    resolution-class now: it falls through to the enumerated path, whose own
    range check types the refusal."""
    _install_backend(monkeypatch, devices=[((0x0403, _OFFICIAL_PID, "610042"), 1)])
    for selector in ("0403:6001/2", "ftdi://0x0403:0x6001/2"):
        with pytest.raises(
            RuntimeError, match="live_provider_interface_out_of_range:"
        ) as excinfo:
            open_ftdi(selector)
        assert "1..1" in str(excinfo.value)


# -- folds A and D: pyftdi's URL locator semantics, the serial-verification
# -- net, and the canonical attempt URL


@pytest.mark.parametrize(
    "text",
    [
        "ftdi://0x0403:0x6001:1/1",
        "ftdi://0x0403:0x6001:0/1",
        "ftdi://0x0403:0x6001:00000000/1",
        "ftdi://0x0403:0x6001:0x1b/1",
    ],
)
def test_a_url_serial_pyftdi_reads_as_an_index_refuses_at_parse(text: str) -> None:
    """Fold A: a URL-form serial that is a bare number with value <= 255 is
    refused at the parse boundary naming the ambiguity — pyftdi's URL
    grammar reads such a component as a device index (``to_int`` <= 255 in
    usbtools' enumerate_candidates: ``:1`` selects the first candidate,
    ``:2`` the second), never a serial, so the URL form cannot name that
    device and the message points at the colon form that can.
    Live-reproduced by the refute lane, twice: this spelling OPENED a
    different device while the colon spelling correctly refused."""
    with pytest.raises(
        RuntimeError, match="live_provider_selector_malformed:"
    ) as excinfo:
        ftdi_module._parse_ftdi_selector(text)
    message = str(excinfo.value)
    assert "index" in message
    assert "<vid>:<pid>:<serial>" in message


def test_a_url_serial_pyftdi_misreads_never_opens_the_wrong_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fold A's net, driven on the fake that now models pyftdi's INDEX
    semantics: a serial spelling the parse accepts (``2B`` — pyftdi's
    ``to_int`` reads the B-suffixed decimal 2) selects the SECOND candidate
    in pyftdi, a device the selector did not name. The ladder verifies the
    opened device's serial after ``open_from_url`` succeeds; on mismatch it
    CLOSES the device and falls through to the enumerated fallback, whose
    serial filter finds zero and refuses naming both serials. A green arm
    against a fake still modelling serial semantics proves nothing — that
    model is what hid the wrong-device open."""
    usbtools, _core = _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
            ((0x0403, _OFFICIAL_PID, "700001"), 1),
        ],
    )
    with pytest.raises(
        RuntimeError, match="live_provider_device_unavailable:"
    ) as excinfo:
        open_ftdi("ftdi://0x0403:0x6001:2B/1")
    message = str(excinfo.value)
    assert "enumeration found 0 matching device(s)" in message
    assert "opened a device reporting serial" in message
    assert "'700001'" in message and "'2B'" in message
    assert _INSTANCES[-1].closed == 1  # the wrong device was closed, not kept
    assert _INSTANCES[-1].open_calls == []  # the fallback's filter refused first
    assert usbtools.find_all_calls  # the enumerated fallback really ran


def test_the_url_attempt_is_canonicalised_to_explicit_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fold D: the URL handed to pyftdi is BUILT from the parsed ints with
    explicit ``0x`` spellings — pyftdi's ``to_int`` reads BARE digits as
    decimal, so passing the raw operator string (``ftdi://123:456/1``,
    which this grammar parsed as 0x123/0x456) would hand pyftdi a different
    vendor and product than the selector named. The grammar's ids are
    hexadecimal in both forms; the canonical attempt URL makes pyftdi read
    the pair the parser read."""
    _install_backend(monkeypatch, devices=[((0x123, 0x456, None), 1)])
    driver = open_ftdi("ftdi://123:456/1")
    assert isinstance(driver, ftdi_module._PyftdiDriver)
    assert _INSTANCES[-1].url_calls == ["ftdi://0x0123:0x0456/1"]


def test_a_verified_url_serial_opens_directly_without_a_fallback_detour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The honest other half of fold A's net: a URL-form serial pyftdi
    reads as a serial (numeric above 255, or alphabetic) that the opened
    device really reports opens directly through the incumbent arm — the
    verification adds no fallback detour, so the net costs nothing on the
    legal path."""
    usbtools, _core = _install_backend(
        monkeypatch, devices=[((0x0403, _OFFICIAL_PID, "610042"), 1)]
    )
    driver = open_ftdi("ftdi://0x0403:0x6001:610042/1")
    assert isinstance(driver, ftdi_module._PyftdiDriver)
    assert usbtools.find_all_calls == []
    assert _INSTANCES[-1].open_calls == []
    assert _INSTANCES[-1].url_calls == ["ftdi://0x0403:0x6001:610042/1"]


def test_a_port_beyond_the_device_interface_count_refuses_before_the_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ifcount`` is a COUNT, not an index — a selector asking for port 3
    on a 2-interface device refuses
    ``live_provider_interface_out_of_range:`` at this boundary, naming the
    port and the count, before any open (pyftdi's own guard is late, and
    its ``/0`` coercion is silent)."""
    _install_backend(monkeypatch, devices=[((0x0403, _MULTI_PID, "A1"), 2)])
    with pytest.raises(
        RuntimeError, match="live_provider_interface_out_of_range:"
    ) as excinfo:
        open_ftdi("0403:6010:A1/3")
    assert "1..2" in str(excinfo.value)
    assert _INSTANCES[-1].open_calls == []


def test_a_port_within_the_count_reaches_the_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The honest other half of the range check: port 2 on a 2-interface
    device is legal and reaches ``open`` with ``interface=2`` — the
    multi-interface choice the grammar promises."""
    _install_backend(monkeypatch, devices=[((0x0403, _MULTI_PID, "A1"), 2)])
    assert isinstance(open_ftdi("0403:6010:A1/2"), ftdi_module._PyftdiDriver)
    assert _INSTANCES[-1].open_calls[0]["interface"] == 2


def test_resolution_bypasses_pyftdis_device_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``UsbTools`` caches ``find_all`` results until a flush — a long-lived
    host would otherwise see phantom devices after an unplug and miss a
    re-plug. The ladder enumerates with ``nocache=True``: resolution sees
    the bus as it is NOW. The fake's per-pair cache is the miniature:
    without the bypass the second resolve below serves the stale empty set
    and this arm reddens."""
    usbtools, _core = _install_backend(monkeypatch, devices=[])
    with pytest.raises(RuntimeError, match="live_provider_device_unavailable:"):
        open_ftdi("0403:d1a4")
    replug = (FakeDescriptor(0x0403, _OEM_PID, None), 1)  # the re-plug
    usbtools.devices.append(replug)  # what the fresh enumeration must see
    _INVENTORY.append(replug)  # what the direct open resolves against
    assert isinstance(open_ftdi("0403:d1a4"), ftdi_module._PyftdiDriver)
    assert usbtools.nocache_flags == [True, True]


def test_the_malformed_prefix_reaches_the_connect_caller_unwrapped(
    monkeypatch: pytest.MonkeyPatch, plugin: Any
) -> None:
    """The type pin at the seam boundary: inside
    ``PluginSession.connect``'s factory call a ``RuntimeError`` passes
    through unwrapped while every other type is buried in
    ``standalone_plugin_connect:`` wrapping — so the connect-time refusal
    prefixes raise ``RuntimeError`` and the caller sees them verbatim,
    seam-mapped ``not_ready``."""
    _install_backend(monkeypatch)
    session = ftdi_module.ftdi_plugin_session(plugin, "0403/d1a4")
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(session.connect())
    assert str(excinfo.value).startswith("live_provider_selector_malformed:")
    assert "standalone_plugin_connect:" not in str(excinfo.value)


def test_the_out_of_range_prefix_reaches_the_connect_caller_unwrapped(
    monkeypatch: pytest.MonkeyPatch, plugin: Any
) -> None:
    """The interface-range prefix is a connect-time ``RuntimeError`` too —
    the operator picks a legal port from the refusal, not from a wrapped
    500."""
    _install_backend(monkeypatch, devices=[((0x0403, _MULTI_PID, "A1"), 2)])
    session = ftdi_module.ftdi_plugin_session(plugin, "0403:6010:A1/3")
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(session.connect())
    assert str(excinfo.value).startswith("live_provider_interface_out_of_range:")
    assert "standalone_plugin_connect:" not in str(excinfo.value)


def test_the_ambiguity_prefix_reaches_the_connect_caller_unwrapped(
    monkeypatch: pytest.MonkeyPatch, plugin: Any
) -> None:
    """The ambiguity prefix is a connect-time ``RuntimeError`` — the
    operator picks a twin from the refusal verbatim."""
    _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
            ((0x0403, _OFFICIAL_PID, "700001"), 1),
        ],
    )
    session = ftdi_module.ftdi_plugin_session(plugin, "0403:6001")
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(session.connect())
    assert str(excinfo.value).startswith("live_provider_device_ambiguous:")
    assert "standalone_plugin_connect:" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Enumeration: the family-scoped vendor scan and the emitted selectors
# ---------------------------------------------------------------------------


def test_enumeration_walks_registered_vendors_and_emits_one_selector_per_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enumeration replacement: pyftdi's product tables are never
    consulted — the scan is pyusb-level over the vendor ids the
    ``PROVIDER_EXECUTORS`` registry declares. ONE SELECTOR PER INTERFACE,
    ``1..ifcount`` (rev 7 fold 4): the FT2232H-shaped 2-interface device
    lists both ports as independently pickable selectors and ``/1`` always
    means the first interface, which is the control port. The serial rides
    before the interface when the device reports one; rows sort for
    determinism; every emitted selector round-trips the grammar."""
    _, core = _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OEM_PID, None), 1),
            ((0x0403, _MULTI_PID, "A1"), 2),
            ((0x1F71, 0x0111, "B2"), 1),  # a vendor no executor registers
        ],
    )
    selectors = ftdi_module._ftdi_scan_selectors()
    # Rows sort by (vid, pid, serial, ifcount): 0x6010 < 0x0d1a4 numerically.
    assert selectors == [
        "ftdi://0x0403:0x6010:A1/1",
        "ftdi://0x0403:0x6010:A1/2",
        "ftdi://0x0403:0xd1a4/1",
    ]
    assert core.finds  # the scan queried the registered vendors
    assert 0x1F71 not in core.finds  # an unregistered vendor is not scanned
    for text in selectors:  # every emitted selector round-trips the grammar
        selector = ftdi_module._parse_ftdi_selector(text)
        assert selector.vid == 0x0403
        assert selector.port in (1, 2)
        assert selector.serial == (None if "0xd1a4" in text else "A1")


def test_the_emitted_selectors_open_through_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What discovery offers, the ladder opens: every emitted selector of
    the 2-interface OEM device connects end to end over the fake backend
    (the URL arm, via the transient registration) — and the colon form of
    the same rows opens through the fallback's direct open at each port's
    own interface index, so the multi-port choice the scan promises is real
    on both arms."""
    _install_backend(monkeypatch, devices=[((0x0403, _OEM_PID, "A1"), 2)])
    selectors = ftdi_module._ftdi_scan_selectors()
    assert len(selectors) == 2
    for text in selectors:
        assert isinstance(open_ftdi(text), ftdi_module._PyftdiDriver)
    assert [i.url_calls for i in _INSTANCES[:2]] == [
        ["ftdi://0x0403:0xd1a4:A1/1"],
        ["ftdi://0x0403:0xd1a4:A1/2"],
    ]
    assert isinstance(open_ftdi("0403:d1a4:A1/1"), ftdi_module._PyftdiDriver)
    assert isinstance(open_ftdi("0403:d1a4:A1/2"), ftdi_module._PyftdiDriver)
    calls = [c for i in _INSTANCES[2:] for c in i.open_calls]
    assert [call["interface"] for call in calls] == [1, 2]


def test_mixed_serial_twins_list_both_rows_not_an_untyped_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fold B (refute lane 2): two devices under one vid/pid where one
    reports no serial and one does must BOTH list — the rows sort with a
    None-safe key inside the guarded block. The bare ``sorted(rows)`` that
    sat OUTSIDE the ``try`` tuple-compared ``None`` against ``str`` and
    raised ``TypeError`` past every typed refusal, so the seam's FTDI branch
    answered an untyped 500 and BOTH devices became invisible."""
    _install_backend(
        monkeypatch,
        devices=[
            ((0x0403, _OFFICIAL_PID, None), 1),
            ((0x0403, _OFFICIAL_PID, "610042"), 1),
        ],
    )
    selectors = ftdi_module._ftdi_scan_selectors()
    assert selectors == [
        "ftdi://0x0403:0x6001/1",  # the no-serial row sorts first
        "ftdi://0x0403:0x6001:610042/1",
    ]


def test_enumeration_failure_names_the_class_and_the_way_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrong-cause text is gone: an enumeration failure names the
    exception class and the operator's way out (``--device``), never the
    fabricated "(no USB backend, or a busy bus)" guess."""
    _, core = _install_backend(monkeypatch, devices=[])

    def _no_backend(find_all: bool = False, idVendor: int | None = None) -> list[Any]:
        raise FakeUSBError("No backend available")

    core.find = _no_backend  # type: ignore[method-assign]
    with pytest.raises(
        RuntimeError, match="live_provider_enumeration_failed:"
    ) as excinfo:
        ftdi_module._ftdi_scan_selectors()
    assert "FakeUSBError" in str(excinfo.value)
    assert "no USB backend, or a busy bus" not in str(excinfo.value)
    assert "--device" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The LIVE arms (marker live_ftdi; CI deselects it, the arms also self-skip)
# ---------------------------------------------------------------------------


def _registered_family_vendors() -> set[int]:
    return {
        vid
        for executor in ftdi_module.PROVIDER_EXECUTORS.values()
        for vid in executor.vendor_ids
    }


@pytest.mark.live_ftdi
def test_live_scan_lists_every_attached_ftdi_device() -> None:
    """LIVE, the only arm that touches a real bus: whenever any FTDI-class
    device is attached (a direct pyusb lookup over the registered family
    vendors is the discriminator — a different call than the scan it
    gates), the family scan returns at least one canonical selector row.
    Skips when no device is attached or no USB backend exists; no device
    identity is asserted or named."""
    import usb.core

    from benchweave_sdk_server.ftdi import _ftdi_scan_selectors

    try:
        attached = any(
            usb.core.find(idVendor=vid) is not None
            for vid in _registered_family_vendors()
        )
    except Exception:
        pytest.skip("no USB backend on this host")
    if not attached:
        pytest.skip("no FTDI-class device attached to this host")
    selectors = _ftdi_scan_selectors()
    assert selectors, "a device answered the family lookup but the scan listed none"
    for text in selectors:
        assert text.startswith("ftdi://0x")
        selector = ftdi_module._parse_ftdi_selector(text)
        assert selector.port >= 1  # every row is a legal, re-parseable selector


@pytest.mark.live_ftdi
def test_live_the_ladder_opens_the_scan_derived_selector(plugin: Any) -> None:
    """LIVE, the PR-1 acceptance leg this suite can carry: the scan's own
    first selector — derived, never hardcoded — opens through the ladder's
    direct-open arm and the handle closes again. The identify conversation
    belongs to a plugin's adapter (the synthetic bring-up fixture speaks a
    protocol a generic FTDI device does not); what PR-1 proves on hardware
    is the scan → canonical selector → open path itself."""
    import usb.core

    from benchweave_sdk_server.ftdi import _ftdi_scan_selectors, open_ftdi

    try:
        attached = any(
            usb.core.find(idVendor=vid) is not None
            for vid in _registered_family_vendors()
        )
    except Exception:
        pytest.skip("no USB backend on this host")
    if not attached:
        pytest.skip("no FTDI-class device attached to this host")
    selectors = _ftdi_scan_selectors()
    assert selectors
    text = selectors[0]
    # The colon form of the same device, derived from the scan's own row.
    body = text[len("ftdi://") :]
    netloc, _, interface = body.rpartition("/")
    colon_form = netloc.replace("0x", "") + f"/{interface}"
    driver = open_ftdi(colon_form)
    try:
        assert isinstance(driver, ftdi_module._PyftdiDriver)
    finally:
        driver.close()


@pytest.mark.live_ftdi
def test_live_the_url_index_serial_spelling_refuses_typed() -> None:
    """LIVE, fold A's bench leg — the spelling the refute lane reproduced
    OPENING A WRONG DEVICE (a URL-form third component pyftdi reads as a
    device index): derived from the scan's own first selector, never
    hardcoded, the same vid/pid with the third component set to ``1``
    refuses at the parse boundary naming the index reading, before any USB
    claim happens."""
    import usb.core

    from benchweave_sdk_server.ftdi import _ftdi_scan_selectors, open_ftdi

    try:
        attached = any(
            usb.core.find(idVendor=vid) is not None
            for vid in _registered_family_vendors()
        )
    except Exception:
        pytest.skip("no USB backend on this host")
    if not attached:
        pytest.skip("no FTDI-class device attached to this host")
    row = _ftdi_scan_selectors()[0]
    netloc = row[len("ftdi://") :].rsplit("/", 1)[0]
    pair = ":".join(netloc.split(":")[:2])  # the scan row's own vid:pid
    trap = f"ftdi://{pair}:1/1"
    with pytest.raises(RuntimeError, match="live_provider_selector_malformed:") as exc:
        open_ftdi(trap)
    assert "index" in str(exc.value)


@pytest.mark.live_ftdi
def test_live_a_url_selector_with_the_reported_serial_opens_and_closes() -> None:
    """LIVE, fold A's positive control: the scan's first selector, when its
    row carries a serial, opens over the URL arm with the post-open serial
    verification running against real hardware — and the device is closed
    again, left unclaimed."""
    import usb.core

    from benchweave_sdk_server.ftdi import _ftdi_scan_selectors, open_ftdi

    try:
        attached = any(
            usb.core.find(idVendor=vid) is not None
            for vid in _registered_family_vendors()
        )
    except Exception:
        pytest.skip("no USB backend on this host")
    if not attached:
        pytest.skip("no FTDI-class device attached to this host")
    selectors = _ftdi_scan_selectors()
    serialled = [
        text
        for text in selectors
        if ftdi_module._parse_ftdi_selector(text).serial is not None
    ]
    if not serialled:
        pytest.skip("no attached device reports a serial the selector can carry")
    driver = open_ftdi(serialled[0])
    try:
        assert isinstance(driver, ftdi_module._PyftdiDriver)
    finally:
        driver.close()
