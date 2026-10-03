"""Synthetic setpoint exchanges only; not a commercial instrument driver."""
import math


def transaction(verb, value=None):
    if verb == "identify":
        return {"kind": "stream_exchange", "data": b"ID?\n",
                "max_bytes": 128, "termination": "lf", "exact_bytes": None}
    if verb == "read":
        return {"kind": "stream_exchange", "data": b"LIM?\n",
                "max_bytes": 128, "termination": "lf", "exact_bytes": None}
    if verb == "write":
        return {"kind": "stream_exchange", "data": f"LIM {value:g}\n".encode("ascii"),
                "max_bytes": 128, "termination": "lf", "exact_bytes": None}
    raise ValueError(f"Unknown verb: {verb}")


def parse_identity(raw):
    if raw != b"BenchWeave Labs,setpoint-demo,SIM-SP1,1.0.0\n":
        raise ValueError("Unexpected identity")
    return {"manufacturer": "BenchWeave Labs", "model": "setpoint-demo", "serial": "SIM-SP1",
            "firmware": "1.0.0", "source": "device"}


def parse_limit(raw):
    if not isinstance(raw, bytes) or len(raw) > 128 or not raw.endswith(b"\n"):
        raise ValueError("Incomplete frame")
    value = float(raw.decode("ascii"))
    if not math.isfinite(value) or not 0.0 <= value <= 5.0:
        raise ValueError("Limit outside the declared range")
    return value


def parse_ack(raw):
    if raw == b"OK\n":
        return True
    if raw == b"ERR\n":
        return False
    raise ValueError("Unexpected acknowledgement")
