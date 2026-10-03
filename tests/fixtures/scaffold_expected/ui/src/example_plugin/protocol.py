"""Synthetic exchanges only; this is not a commercial instrument driver."""
import math


def transaction(verb):
    return {"kind": "stream_exchange", "data": b"ID?\n" if verb == "identify" else b"V?\n",
            "max_bytes": 128, "termination": "lf", "exact_bytes": None}


def parse_identity(raw):
    if raw != b"SDK Example,demo,SIM001,1.0.0\n":
        raise ValueError("Unexpected identity")
    return {"manufacturer": "SDK Example", "model": "demo", "serial": "SIM001",
            "firmware": "1.0.0", "source": "device"}


def parse_voltage(raw):
    if not isinstance(raw, bytes) or len(raw) > 128 or not raw.endswith(b"\n"):
        raise ValueError("Incomplete frame")
    value = float(raw.decode("ascii"))
    if not math.isfinite(value):
        raise ValueError("Nonfinite reading")
    return value
