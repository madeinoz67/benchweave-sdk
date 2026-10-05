# author: Stephen Eaton
"""Synthetic binary-frame exchanges; not a commercial instrument driver.

The adapter speaks the generic OTDP section 8.1 ``stream_send`` /
``stream_receive`` shape (issue #394's plugin class): commands are frames
on the wire, binary payload frames carry little-endian floats, and the
drain idiom (receive until the quiet-line ``b""``) consumes unsolicited
status frames before every command — the guide's telemetry-drain pattern.
"""
import math
import struct

MAX_FRAME_BYTES = 128
SAMPLE_FRAME_BYTES = 16  # two little-endian float64 samples

IDENTITY_FRAME = b"BenchWeave Labs,frames-demo,SIM-BF1,1.0.0\n"
STATUS_FRAME = b"STAT\x00\n"


def probe():
    """One drain receive: a quiet-line probe, not a command."""
    return {"kind": "stream_receive", "max_bytes": MAX_FRAME_BYTES,
            "termination": "lf", "exact_bytes": None}


def send_frame(data):
    return {"kind": "stream_send", "data": data}


def recv_frame(max_bytes=None, exact=None):
    bounds = {"kind": "stream_receive", "max_bytes": max_bytes or MAX_FRAME_BYTES,
              "termination": "lf", "exact_bytes": exact}
    return bounds


def identify_frame():
    return b"*IDN?\n"


def read_frame():
    return b"AVG?\n"


def write_frame(value):
    return b"SA" + struct.pack("<f", float(value)) + b"\n"


def capture_frame(count):
    return f"CAP {count:d}\n".encode("ascii")


async def drain(services, context):
    """Receive until the quiet line: unsolicited status frames are consumed
    deterministically before the next command is sent."""
    while True:
        reply = await services.transfer(probe(), context)
        if reply["data"] == b"":
            return


def parse_identity(raw):
    if raw != IDENTITY_FRAME:
        raise ValueError("Unexpected identity")
    return {"manufacturer": "BenchWeave Labs", "model": "frames-demo",
            "serial": "SIM-BF1", "firmware": "1.0.0", "source": "device"}


def parse_sample(raw):
    if (not isinstance(raw, bytes) or len(raw) != 5
            or not raw.endswith(b"\n")):
        raise ValueError("Incomplete sample frame")
    value = struct.unpack("<f", raw[:4])[0]
    if not math.isfinite(value) or not 0.0 <= value <= 5.0:
        raise ValueError("Sample outside the declared range")
    return value


def parse_ack(raw):
    if raw == b"OK\n":
        return True
    if raw == b"ERR\n":
        return False
    raise ValueError("Unexpected acknowledgement")
