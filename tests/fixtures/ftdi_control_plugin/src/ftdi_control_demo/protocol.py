# author: Stephen Eaton
"""The fixture plugin's own wire truth: builders over module constants.

The constants below are deliberately the ONLY place this plugin spells its
control parameters and frame bytes. The bring-up journal in this fixture
package (``bring-up-journal.json``) spells the SAME values independently —
two sources that must agree is exactly what a recorded journal proves: a
mutated builder constant diverges from the journal and the parity assertion
fails at the first divergent op. Nothing in this module reads the journal.
"""

#: The init chain's latency timer, one byte (the contract's declared range).
INIT_LATENCY_MS = 16

#: The init chain's line rate.
INIT_BAUD = 115200

#: The init chain's pin-direction mask (low nibble driven).
INIT_BITMASK = 0x0F

#: The init chain's interface mode (a synthetic-but-conforming mode byte).
INIT_BITMODE = 0x40

#: The purge the init chain opens with (drain the receive side first).
INIT_PURGE_QUEUE = "rx"

#: The idle pin byte the bring-up polls before the bitstream chunk.
PINS_IDLE = 0x00

#: The DONE bit the post-chunk pin poll gates on.
DONE_MASK = 0x80

#: The bitstream chunk the bring-up loads over the data pipe (one chunk,
#: under the journal's bulk bound — the recorded conversation's shape).
BITSTREAM_CHUNK = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE])

#: The status conversation's request frame: sync, then the status opcode.
STATUS_FRAME = bytes([0x55, 0xA1])

#: The status reply's recorded shape: marker, counter, index, reading.
STATUS_REPLY_LEN = 4

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
        "exact_bytes": STATUS_REPLY_LEN,
    }


def decode_status(data: bytes) -> int:
    """Decode the status reply's reading byte (``55 A1`` asks; the reply is
    ``C2 00 <counter> <reading>``)."""
    if not isinstance(data, bytes) or len(data) < STATUS_READING_INDEX + 1:
        raise ValueError("expected a four-byte status reply")
    return data[STATUS_READING_INDEX]
