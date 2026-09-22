"""The user guide's standalone serial host example is executable and correct.

The example lives in ``user_guide/plugin-sdk.qmd`` (it is author-side tooling,
not an SDK module). This file extracts the first fenced block that defines it,
executes it, and holds it to OTDP section 8.1: a freshly scaffolded plugin
must run through it end to end, and the transaction rules it claims must hold.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import re
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk.capture import StandaloneCaptureWriter
from benchweave_sdk.interfaces import CaptureServices, OperationContext
from benchweave_sdk.scaffold import create_project

GUIDE = Path(__file__).resolve().parents[1] / "user_guide" / "plugin-sdk.qmd"


def _example() -> dict[str, Any]:
    text = GUIDE.read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    source = next(block for block in blocks if "class SerialStandaloneHost" in block)
    namespace: dict[str, Any] = {"__name__": "guide_serial_host"}
    exec(compile(source, str(GUIDE), "exec"), namespace)  # the repository's own guide text
    return namespace


EXAMPLE = _example()
Host = EXAMPLE["SerialStandaloneHost"]
BenchContext = EXAMPLE["BenchContext"]


class FakePort:
    """pyserial's surface: ``read`` returns what is buffered (b'' stands for its timeout)."""

    def __init__(self, inbound: bytes = b"", replies: dict[bytes, bytes] | None = None) -> None:
        self.inbound = bytearray(inbound)
        self.replies = replies or {}
        self.written: list[bytes] = []
        self.closed = 0
        self.reads = 0

    def write(self, data: bytes) -> int:
        self.written.append(data)
        self.inbound += self.replies.get(data, b"")
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        if not out:
            time.sleep(0.001)  # the port's own short timeout
        return out

    def close(self) -> None:
        self.closed += 1


def _members(protocol: type) -> set[str]:
    names: set[str] = set()
    for klass in protocol.__mro__:
        if klass.__name__ in {"Protocol", "Generic", "object"}:
            continue
        names |= {name for name in vars(klass) if not name.startswith("_")}
    return names


def _receive(**fields: Any) -> dict[str, Any]:
    return {
        "kind": "stream_receive",
        "max_bytes": 64,
        "termination": "lf",
        "exact_bytes": None,
        **fields,
    }


def test_the_host_carries_all_eight_members_and_the_context_all_of_its_own() -> None:
    assert _members(CaptureServices) <= set(dir(Host))
    assert len(_members(CaptureServices)) == 8
    assert _members(OperationContext) <= set(dir(BenchContext("op", 1.0)))


def test_a_scaffolded_plugin_runs_end_to_end_through_the_host(tmp_path: Path) -> None:
    create_project(tmp_path / "proj", "serialdemo_plugin")
    sys.path.insert(0, str(tmp_path / "proj" / "src"))
    try:
        adapter = importlib.import_module("serialdemo_plugin.adapter")
        port = FakePort(replies={b"ID?\n": b"SDK Example,demo,SIM001,1.0.0\n", b"V?\n": b"3.3\n"})
        host = Host(port, writer=StandaloneCaptureWriter(tmp_path / "captures"))

        async def run() -> list[dict[str, Any]]:
            plugin = adapter.create_plugin()
            await plugin.open({}, host, BenchContext("open", 2.0))
            results = []
            for verb, args in (("identify", {}), ("read", {"parameter": "voltage"})):
                context = BenchContext(f"op-{verb}", 2.0)
                request = {"operation_id": context.operation_id, "verb": verb, "arguments": args}
                results.append(await plugin.execute(request, context))
            await plugin.close(BenchContext("close", 2.0))
            return results

        identify, read = asyncio.run(run())
    finally:
        sys.path.remove(str(tmp_path / "proj" / "src"))
        for name in [m for m in sys.modules if m.startswith("serialdemo_plugin")]:
            del sys.modules[name]
    assert identify["status"] == "ok" and identify["data"]["serial"] == "SIM001"
    assert read["status"] == "ok" and read["data"]["value"] == pytest.approx(3.3)
    assert port.written == [b"ID?\n", b"V?\n"] and port.closed == 1


def test_exact_bytes_takes_precedence_and_frames_a_binary_protocol() -> None:
    port = FakePort(b"\xf0\xa1\x03\x02AB\n\xf0")
    host = Host(port)

    async def run() -> tuple[bytes, bytes, bytes]:
        header = await host.transfer(_receive(exact_bytes=4), BenchContext("h", 1.0))
        body = await host.transfer(_receive(exact_bytes=2), BenchContext("b", 1.0))
        line = await host.transfer(_receive(), BenchContext("l", 1.0))
        return header["data"], body["data"], line["data"]

    assert asyncio.run(run()) == (b"\xf0\xa1\x03\x02", b"AB", b"\n")


def test_an_incomplete_frame_is_never_returned_and_is_kept_for_the_next_receive() -> None:
    port = FakePort(b"3.3")
    host = Host(port)
    with pytest.raises(TimeoutError):
        asyncio.run(host.transfer(_receive(), BenchContext("slow", 0.05)))
    port.inbound += b"\r\n"
    reply = asyncio.run(host.transfer(_receive(termination="crlf"), BenchContext("again", 1.0)))
    assert reply == {"data": b"3.3\r\n"}


def test_a_line_longer_than_max_bytes_is_refused_and_discarded() -> None:
    host = Host(FakePort(b"123456\nOK\n"))
    with pytest.raises(ValueError, match="no terminator"):
        asyncio.run(host.transfer(_receive(max_bytes=4), BenchContext("long", 1.0)))
    tail = asyncio.run(host.transfer(_receive(max_bytes=8), BenchContext("tail", 1.0)))
    assert tail == {"data": b"56\n"}


@pytest.mark.parametrize(
    "transaction",
    [
        {"kind": "stream_exchange", "data": b"X\n", "max_bytes": 8, "termination": "lf"},
        {**_receive(), "timeout_ms": 5},
        _receive(termination="eom"),
        _receive(exact_bytes=65),
        _receive(max_bytes=0),
        _receive(max_bytes=True),
        {"kind": "stream_send", "data": "text"},
        {"kind": "can_send", "id": 1, "extended": False, "fd": False, "data": b""},
    ],
)
def test_transactions_outside_section_8_1_are_refused_before_any_io(
    transaction: dict[str, Any],
) -> None:
    port = FakePort(b"ignored\n")
    with pytest.raises(ValueError):
        asyncio.run(Host(port).transfer(transaction, BenchContext("bad", 1.0)))
    assert port.written == [] and port.reads == 0


def test_a_cancelled_operation_transmits_nothing_and_a_closed_port_is_a_connection_error() -> None:
    port = FakePort()
    host = Host(port)
    context = BenchContext("cancelled", 1.0)
    context.cancel()
    with pytest.raises(TimeoutError):
        asyncio.run(host.transfer({"kind": "stream_send", "data": b"X"}, context))
    assert port.written == []
    asyncio.run(host.close_transport(BenchContext("c", 1.0)))
    asyncio.run(host.close_transport(BenchContext("c2", 1.0)))
    assert port.closed == 1
    with pytest.raises(ConnectionError):
        asyncio.run(
            host.transfer({"kind": "stream_send", "data": b"X"}, BenchContext("after", 1.0))
        )


def test_capture_goes_through_the_standalone_writer(tmp_path: Path) -> None:
    host = Host(FakePort(), writer=StandaloneCaptureWriter(tmp_path, formats=("raw_binary",)))

    async def run() -> dict[str, Any]:
        context = BenchContext("cap", 2.0)
        await host.artifact_append("cap-1", b"\x01\x02", context)
        await host.artifact_append("cap-1", b"\x03", context)
        return await host.artifact_finalise(
            "cap-1", {"format": "raw_binary", "started_at": "2026-09-24T00:00:00Z"}, context
        )

    manifest = asyncio.run(run())
    assert manifest["sha256"] == hashlib.sha256(b"\x01\x02\x03").hexdigest()
    assert (tmp_path / "cap-1" / "cap-1.bin").read_bytes() == b"\x01\x02\x03"


def test_evidence_is_kept_and_appended_as_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"
    host = Host(FakePort(), evidence_path=path)
    asyncio.run(
        host.record_evidence(
            {"kind": "device_error", "entry": {"code": "E1", "message": "m"}},
            BenchContext("ev", 1.0),
        )
    )
    assert host.evidence[0]["operation_id"] == "ev" and host.evidence[0]["at"].endswith("Z")
    assert path.read_text(encoding="utf-8").count("\n") == 1
