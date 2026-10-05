---
name: example-plugin-plugin-development
description: Author, implement, check and release the example_plugin BenchWeave
  device plugin - elicitation questions keyed to the real descriptor
  surfaces, adapter discipline, standalone-MCP shape and release mechanics.
---

# Developing the example_plugin plugin

Work prompt-first: establish facts before editing, implement against mocks,
then review and release. The descriptor is the contract; every command you
wire must trace to evidence. Do not invent commands or capabilities.

## 1. Elicitation - ask before generating

Ask all of these before writing the descriptor, adapter or manifest. Each
question names the real surface it fills.

**Device identity** (`identity`): manufacturer and exact model? Which
`strategy` - `scpi_idn`, `uart_identity`, `commissioned` or `adapter`?
`firmware_policy` `listed` (then which `supported_firmware` versions?) or
`commissioning_required`?

**Transport** (`transport`, nine types): `serial`, `uart_scpi`,
`uart_json`, `lan_scpi`, `usbtmc`, `can`, `i2c`, `spi` or `custom`? Which
`connection_key`? Which settings - serial/uart: `baud`, `data_bits`,
`parity`, `stop_bits`, `rtscts`, `max_frame_bytes` (uart_json also
`framing`; uart_scpi also `max_response_bytes`, `read_termination`,
`write_termination`); lan_scpi: `port`, `protocol`, `read_termination`,
`write_termination`, `max_response_bytes`; usbtmc: `vid`, `pid`,
`read_termination`, `write_termination`, `max_response_bytes`; can:
`receive_id`, `fd`, `extended`, `payload_length`; i2c: `address`; spi:
`mode`, `speed_hz`, `bits_per_word`; custom: `protocol_reference`?

**Class and profiles** (`profiles`, `actions`): which of the twelve OTDP
classes - `otdp.dc_psu/1.0.0`, `otdp.dmm/1.0.0`, `otdp.oscilloscope/1.0.0`,
`otdp.logic_analyser/1.0.0`, `otdp.function_generator/1.0.0`,
`otdp.electronic_load/1.0.0`, `otdp.smu/1.0.0`, `otdp.daq/1.0.0`,
`otdp.embedded_controller/1.0.0`, `otdp.switch_matrix/1.0.0`,
`otdp.spectrum_analyser/1.0.0`, `otdp.vna/1.0.0`? Which profile ids to
declare, and which class action contracts to adopt?

**Operations** (`capabilities` must equal `operations` keys - S01): which
of the ten verbs - `identify`, `read`, `write`, `invoke`, `capture`,
`reset`, `self_test`, `get_errors`, `stream_subscribe`,
`stream_unsubscribe`? Per verb the operation policy: `timeout_ms`,
`side_effect` (`none` or `state_change`), `retry` (`never` or
`idempotent`), `cancellable`, `completion` (`dispatched`, `acknowledged`,
`readback` or `physical`)?

**Parameters** (`parameters`): per parameter the `name`, `type`
(`float`, `int`, `bool`, `enum`, `string`), `access` (`ro`, `wo`, `rw`),
`semantic` (`measurement`, `setpoint`, `state`, `configuration`), `unit`,
`description`? A `range` or `enum_values`? `string_constraints`?
`hazard_class` (`unknown`, `none`, `low`, `high`)? `read_policy`
(`max_age_ms`, `destructive`) and `write_policy` (completion, effect,
retry, tolerances, settling)? `binding` kind? Names unique (S01), bounds
not reversed (S02)?

**Channels, capture and streams** (the capture/decode case): `channels`
entries - `id`, `label`, `role`, `quantities`, `parameter_names`? Which
`capture_formats` and `capture_limits`? Which `stream_limits`?

**Diagnostics** (`diagnostics`): self-test and error-reporting surface?
Which of `self_test` / `get_errors` apply?

**Adapter** (`integration.adapter`): `entry_point`, `api_version`,
`version`, `dependencies`, `permissions` (for example
`scoped_transport`)?

**Evidence and provenance** (`provenance`): command sources
(`sources[]` title/reference/revision)? `test_vectors` paths? Evidence
level per report - `structural`, `simulated` or `hardware`?

**Release**: package `kind` - `profile`, `descriptor` or
`implementation`? (See section 5.)

**Safety boundary**: what must never be done without separate authority?
While authoring: do not contact hardware, flash firmware or energise
outputs, and publish nothing without separate authority.

## 2. Firmware development

Keep vendor source and checksum references under `firmware/` and release
notes under `firmware/release-notes/`; they document constraints only.
Decide `listed` (exact supported versions) versus `commissioning_required`
(no implied tested firmware) from real evidence. The SDK does no firmware
discovery and no flashing - ever.

## 3. Adapter creation

Implement `protocol.py` and async `adapter.py` against the real adapter
surface: `open(descriptor, services, context)`, `execute(request,
context)`, `next_event`, `close`. Keep `create_plugin` no-argument and
construction/open free of device I/O. Mark dispatch before transmit,
honour monotonic deadlines and cancellation, never retry silently,
preserve uncertain outcomes, and keep imports relative within this
package or standard-library-only for the gateway loader. The SDK's
`MockHost`/`MockContext` exchanges (see tests/test_plugin.py) are the
reference pattern for exact-exchange tests.


The standalone mock transport serves the transaction dialect that
`vectors.json` declares. The keys are `transaction_dialect` and
`encoding`. A row without a request is a device-initiated frame. The
"Mock transports" section of the SDK user guide states the row contract
and what the mock can and cannot rehearse.

## 4. Standalone MCP server (workflow, not shipped machinery)

The SDK ships no MCP server. To use this plugin standalone, write a
project-local MCP server: construct the adapter via `create_plugin()`,
implement the five-method host contract over a real transport (settings
from the descriptor) - `transfer(transaction, context)`, `monotonic()`,
`utc_now()`, `close_transport(context)`, `record_evidence(entry,
context)` - and expose the descriptor's verbs as MCP tools, keeping the
dispatch-before-transmit, deadline and uncertain-outcome disciplines.
Keep it out of the distributed package unless the owner decides
otherwise.

## 5. Release

Build the wheel and sdist, then prepare the registry manifest with the
exact payload inventory and hashes (`benchweave-sdk inventory` emits the
path/bytes/sha256 rows; the manifest assigns roles). File roles for this
project's files: the skills under `src/example_plugin/skills/` are `skill`;
`descriptor.json` is `descriptor`; `protocol.md` and `vectors.json` are
`test` evidence inputs per the registry specification's role list
(`profile`, `descriptor`, `implementation`, `schema`, `test`,
`documentation`, `licence`, `sbom`, `build_provenance`,
`dependency_lock`, `skill`); the root `CLAUDE.md` is `documentation` if
the publisher ships it at all - it is dev tooling by default. An
`implementation`-kind payload must contain `implementation`, `sbom`,
`build_provenance` and `dependency_lock` entries. Evidence reports carry
their honest level - `structural`, `simulated` or `hardware`; synthetic
results are never hardware qualification. Publication happens only with
the owner's review: publish nothing without separate authority.
