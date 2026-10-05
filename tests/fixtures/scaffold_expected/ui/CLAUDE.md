# Agent notes — the example_plugin plugin project

@AGENTS.md

## This file is yours

`AGENTS.md` above is SDK-managed (upgraded by `benchweave-sdk upgrade`). Keep your
project-specific notes here; they never block an upgrade.

## Mock transport rehearsal

`src/example_plugin/vectors.json` declares the transaction grammar the
standalone mock serves: `transaction_dialect` (`stream_exchange` when
omitted, or `"send_receive"` for binary section 8.1 frames) and `encoding`
(`ascii` when omitted, or `hex`). Rows without a `request` are
device-initiated frames and require `send_receive`; the adapter drains
received frames until the quiet line before each command. Rehearse offline
before hardware: `benchweave-sdk-server serve . --transport mock`, then
connect, read, apply and capture. The mock's exact-match discipline names
the row and both frames on any disagreement; real interleaving, non-serial
transports and timing need `--transport serial` and hardware.
