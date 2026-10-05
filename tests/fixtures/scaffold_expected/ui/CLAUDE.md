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
received frames until the quiet line before each command. Capture at
least TWO full poll cycles: the repeating unit is detected from the
capture, and a truncated capture replays once in captured order. A
drain returns the captured burst once per cycle, then the quiet line.
Rehearse offline before hardware: `benchweave-sdk-server serve .
--transport mock`, then connect, read, apply and capture. The mock's
exact-match discipline names the row and both frames on any
disagreement; it raises immediately on an unservable receive, so a
green rehearsal proves no `timeout_ms` budget fit — real interleaving,
timing, budget fit and non-serial transports need `--transport serial`
and hardware.
