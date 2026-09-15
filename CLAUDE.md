@AGENTS.md

## MANDATORY: Use Gortex MCP tools instead of Read/Grep/Glob

A Gortex daemon is configured machine-wide. Whenever you operate on indexed source, you
MUST prefer graph queries over file reads. Hook posture is configurable; follow every
Gortex hook instruction even when raw `Read` / `Grep` / `Glob` remain callable.

Calibration: the graph narrows scope, it does not replace reading the implementation. For
the symbol you are about to change or depend on, read its full body with
`read(target:{symbol:…})` or `read(operation:"file", …)` — never act on a one-line summary
alone, and be deliberate with behavior-critical code (standards-sync digests and refusal
paths, scaffold output, packaging): read the real implementation, no compressed bodies.
The full per-tool catalog and workflow load via `tools/list` at session start; until this
checkout is tracked, fall back to `Read` and say so — do not start a daemon.
