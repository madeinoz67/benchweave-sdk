# Agent notes — the example_plugin plugin project

@AGENTS.md

## This file is yours

`AGENTS.md` above is SDK-managed (upgraded by `benchweave-sdk upgrade`). Keep your
project-specific notes here; they never block an upgrade.

## Mock transport rehearsal

`src/example_plugin/vectors.json` declares the transaction dialect
that the standalone mock serves. The `transaction_dialect` key has the
value `stream_exchange` when you omit it, or `"send_receive"` for
binary section 8.1 frames. The `encoding` key has the value `ascii`
when you omit it, or `hex`. A row without a `request` is a
device-initiated frame. Device-initiated frames need `send_receive`.
Before each command, the adapter drains received frames until the
quiet line.

Capture at least TWO full poll cycles. The repeating unit is detected
from the capture. A truncated capture repeats the captured order on
every restore. A drain returns the captured burst once per cycle, and
then the quiet line.

Rehearse offline before you use the hardware. Run
`benchweave-sdk-server serve . --transport mock`. Then connect, read,
apply and capture.

The exact-match discipline of the mock gives the row and both frames
on any disagreement. When a receive is unservable, the mock raises at
once. For this reason, a green rehearsal does not prove a `timeout_ms`
budget fit. Real interleaving, timing, budget fit and non-serial
transports need `--transport serial` and hardware.
