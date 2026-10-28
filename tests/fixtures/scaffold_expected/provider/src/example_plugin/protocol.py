"""Synthetic FTDI common-control bring-up builders; not a device driver.

The constants below are the ONLY place this package spells its control
parameters and frame bytes. The pinned provider contract
(ftdi-control-provider.json, byte-equal to the SDK's banked copy) is the
grammar every transaction here must satisfy. Rehearsal without hardware
runs over the SDK's shipped driver double; a bench session records a
journal with `serve --transport ftdi --record`."""
#: The init chain's latency timer, one byte (the contract's declared range).
INIT_LATENCY_MS = 16

#: The init chain's line rate.
INIT_BAUD = 115200

#: The init chain's pin-direction mask (low nibble driven).
INIT_BITMASK = 0x0F

#: The init chain's interface mode (a synthetic-but-conforming mode byte).
INIT_BITMODE = 0x40

#: The drain the init chain opens with (receive side first).
INIT_PURGE_QUEUE = "rx"

#: The idle pin byte the bring-up polls before the bitstream chunk.
PINS_IDLE = 0x00

#: The DONE byte the post-chunk pin poll gates on.
DONE_BYTE = 0x80

#: The bitstream chunk the bring-up loads over the data pipe.
BITSTREAM_CHUNK = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE])

#: The status conversation's request frame: sync, then the status opcode.
STATUS_FRAME = bytes([0x55, 0xA1])

#: The status reply's shape: marker, counter, index, reading.
STATUS_REPLY = bytes([0xC2, 0x00, 0x01, 0x5A])

#: The read reply's reading byte index (the fourth byte of the frame).
STATUS_READING_INDEX = 3


def reset_device() -> dict:
    """The bring-up's first transaction: the device reset."""
    return {"kind": "ftdi_control", "op": "reset_device"}


def purge_rx() -> dict:
    """The bring-up's drain of the receive queue."""
    return {"kind": "ftdi_control", "op": "purge", "queue": INIT_PURGE_QUEUE}


def set_latency() -> dict:
    """The bring-up's latency-timer set."""
    return {"kind": "ftdi_control", "op": "set_latency", "ms": INIT_LATENCY_MS}


def set_baud() -> dict:
    """The bring-up's line-rate set."""
    return {"kind": "ftdi_control", "op": "set_baud", "baud": INIT_BAUD}


def set_bitmode() -> dict:
    """The bring-up's interface-mode set."""
    return {
        "kind": "ftdi_control",
        "op": "set_bitmode",
        "mask": INIT_BITMASK,
        "mode": INIT_BITMODE,
    }


def read_pins() -> dict:
    """One pin-state poll (the idle check and the DONE gate share it)."""
    return {"kind": "ftdi_control", "op": "read_pins"}


def stream_send(data: bytes) -> dict:
    """One send-only stream transaction over the data pipe."""
    return {"kind": "stream_send", "data": data}


def status_exchange() -> dict:
    """One status exchange: the request frame, an exact four-byte reply."""
    return {
        "kind": "stream_exchange",
        "data": STATUS_FRAME,
        "max_bytes": 8,
        "termination": "lf",
        "exact_bytes": len(STATUS_REPLY),
    }


def decode_status(data: bytes) -> int:
    """Decode the status reply's reading byte."""
    if not isinstance(data, bytes) or len(data) < STATUS_READING_INDEX + 1:
        raise ValueError("expected a four-byte status reply")
    return data[STATUS_READING_INDEX]
