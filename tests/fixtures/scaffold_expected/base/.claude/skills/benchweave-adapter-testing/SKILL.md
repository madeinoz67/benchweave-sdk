---
name: benchweave-adapter-testing
description: Use when you write or run adapter tests — MockHost and
  MockContext exchanges, check_operation and check_lifecycle bounds, and
  the dispatch and uncertain-outcome rules.
---

# Adapter testing with SDK mocks

The mocks live in `benchweave_sdk.testing`. The conformance helpers live in
`benchweave_sdk.conformance`. The generated `tests/test_plugin.py` shows the
full pattern for this project.

## Exact-exchange tests

- Make a `MockHost` with an ordered list of `(transaction, response)` pairs.
  Each transfer must match the next scripted transaction exactly. A scripted
  exception is raised, not returned.
- Make a `MockContext` with an operation id and a deadline. The clock never
  moves by itself. Move it with `host.advance(seconds)`. Cancel with
  `context.cancel()`.
- Call `host.assert_complete()` at the end. It fails when a scripted exchange
  was not consumed.

## Conformance helpers

- `check_operation(adapter, request, context)` — validate one response. It
  checks the request schema and the correlation of request and result. Each
  call runs under a wall-clock limit.
- `check_lifecycle(create_plugin, descriptor)` — check a quiet lifecycle. Open
  must not do a device transaction. Close must tolerate repeated calls. Each
  await runs under a wall-clock limit.

## Rules the mocks enforce

- Mark dispatch before transmit. The mock refuses a transmitting transfer that
  has no dispatch marker.
- Keep uncertain outcomes uncertain. An error after dispatch reports an
  unknown dispatch state, never a clean failure.
- Honour the deadline and cancellation before dispatch. A refused operation
  transmits nothing.

## What mocks do not prove

- The wall-clock limits stop cooperative tasks only. Blocking Python, or code
  that suppresses cancellation, needs an isolated process.
- The mocks prove the exchange logic. They do not prove hardware behaviour,
  device timing or qualification.

## Read the docs

The plugin SDK guide covers this in section "3. Run the checks".

---
Maintained by benchweave-sdk 0.7.1; `benchweave-sdk upgrade`
refreshes this skill.
