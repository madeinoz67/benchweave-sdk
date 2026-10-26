# author: Stephen Eaton
"""The fixture plugin's own wire truth: builders over module constants.

The constants below are deliberately the ONLY place this plugin spells its
wire bytes and provider parameters. The replay journals in
``tests/server/test_replay.py`` spell the SAME bytes independently — two
sources that must agree is exactly what a recorded journal proves: a
mutated builder constant diverges from the journal and the replay fails at
the first affected row. Nothing in this module reads the journal."""

#: The provider report id every command rides on (a provider-row param).
REPORT_ID_CMD = 0x01

#: The provider read bound for the identify exchange.
IDENTIFY_MAX_BYTES = 32

#: The command payload the identify exchange sends.
IDENTIFY_PAYLOAD = b"\x90\x00"

#: The page-bits decomposition this fixture SIMULATES (the real dialect's
#: page bits are unproven on hardware — issue #564 keeps journals free of
#: them; this constant exists so the mutation class has a representative).
WIRE_PAGE_BITS = 0x40

#: The status register's low address before the page bits apply.
STATUS_ADDR = 0x02

#: The resync frame's marker and mask bytes.
RESYNC_MARKER = 0xE7
RESYNC_MASK = 0x5A

#: The poll frame's pulse byte.
PULSE_BYTE = 0xA5

#: The frame sync byte every stream frame opens with.
FRAME_SYNC = 0x55

#: The capture verbs' command bytes (start carries the frame count).
CAPTURE_CMD = 0x33
CAPTURE_END = 0x34

#: The capture conversation's shape: four eight-byte sample frames.
SAMPLE_FRAMES = 4
SAMPLE_FRAME_BYTES = 8

#: The bulk configuration blob's length (at or above the journal's bulk
#: bound, so the acceptance journal carries it as a digest-form row).
CONFIG_BLOB_LEN = 10_000


def hid_command() -> dict:
    """The identify command as a provider output-report transaction."""
    return {
        "kind": "hid_output_report",
        "report_id": REPORT_ID_CMD,
        "data": IDENTIFY_PAYLOAD,
    }


def hid_read() -> dict:
    """The identify read as a provider input-report transaction."""
    return {
        "kind": "hid_input_report",
        "report_id": REPORT_ID_CMD,
        "max_bytes": IDENTIFY_MAX_BYTES,
    }


def resync_frame() -> bytes:
    """The resync frame: marker, then the drain mask."""
    return bytes([RESYNC_MARKER, RESYNC_MASK])


def poll_frame() -> bytes:
    """The status poll frame: sync, the page-addressed register, the pulse."""
    return bytes([FRAME_SYNC, STATUS_ADDR | WIRE_PAGE_BITS, PULSE_BYTE])


def capture_frame(frames: int) -> bytes:
    """The capture-start frame: command, then the frame count."""
    return bytes([CAPTURE_CMD, frames])


def capture_end_frame() -> bytes:
    """The capture-end frame: command, then a zero pad."""
    return bytes([CAPTURE_END, 0x00])


def config_blob() -> bytes:
    """The bulk configuration blob (deterministic; the journal carries its
    digest, spelled by an independent expression there)."""
    return bytes((i * 7 + 3) & 0xFF for i in range(CONFIG_BLOB_LEN))


def decode_status(data: bytes) -> int:
    """Decode the status reply's reading byte (the fourth byte of the
    recorded read-reply grammar: ``C2 00 <counter> <reading>``)."""
    if not isinstance(data, bytes) or len(data) < 4:
        raise ValueError("expected a four-byte status reply")
    return data[3]


def stream_send(data: bytes) -> dict:
    """One send-only stream transaction."""
    return {"kind": "stream_send", "data": data}


def stream_receive(max_bytes: int, exact_bytes: int | None) -> dict:
    """One receive transaction with section 8.1 bounds."""
    return {
        "kind": "stream_receive",
        "max_bytes": max_bytes,
        "termination": "lf",
        "exact_bytes": exact_bytes,
    }
