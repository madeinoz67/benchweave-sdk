# benchweave-sdk — agent conventions

The BenchWeave plugin SDK: offline authoring and conformance tooling for OTDP device
plugins. A separate wheel from the gateway, mounted in the main repository at
`packages/sdk` as a git submodule. `README.md` is the five-step quickstart;
`user_guide/plugin-sdk.qmd` is the developer guide (rendered at `user-guide/` on the
docs site).

Prose defers to machine sources: when README/guides/site content contradicts standards-lock, manifests, the compatibility matrix, or vendored schemas, the prose is wrong — correct it against the machine source (principal directive 2026-09-16).

## Doc-home map — what lives here, what lives in the main repository

- **Here:** `user_guide/plugin-sdk.qmd` (the plugin developer guide — moved here
  2026-09-15, migrated into the docs site 2026-09-16),
  `README.md` (quickstart + sister-repo pointer), the vendored standards **copy** under
  `src/benchweave_sdk/standards/` (generated from the lock — the `_GENERATED.txt` stamps
  say *do not edit*; hand-editing it is always wrong), and this repo's own working docs
  under `docs/superpowers/`.
- **Main repository** ([madeinoz67/benchweave](https://github.com/madeinoz67/benchweave)):
  the canonical standards corpus and its export tooling (`standards/` — machine
  artifacts and prose companions together, one tree), the
  compatibility matrix, the architecture contracts, the acceptance/evidence record, the
  SDK test suite (`tests/sdk/`), and `docs/plugin-sdk.md` as a stub pointing here. A
  standards change never lands here first — it lands in the corpus, is exported as a
  bundle, and arrives via `sync-standards`.

## Two-repo discipline

**Single issue stream:** all issues — for either repository — file on the gateway
tracker (`madeinoz67/benchweave/issues`); the `benchweave-sdk` tracker is retired
(principal directive 2026-09-20; first use of the rule was gateway issue #107). SDK
work tracks under a gateway issue, and the SDK PR body notes that no SDK-side issue
exists by design.

This repository is both a standalone clone and a submodule. Every change lands as a
commit **here first, pushed**, and then as a pointer commit in the main repository —
never a pointer to an unpushed SHA, never main-side edits to SDK files. The main
repository's `make sync-sdk-standards` refuses to run against a submodule HEAD that
differs from the committed pointer; that refusal is this discipline enforcing itself.
Before finishing an arc: both repositories' gates green, SDK pushed, pointer committed.

## Gortex first

A Gortex daemon serves this repository machine-wide. On every task here, prefer graph
queries over file reads — `read(operation:"file", …)` for a known file,
`explore`/`search` when the target must be discovered, `change(operation:"impact")`
before mutation, `edit`/`refactor` to mutate. The graph narrows scope; the source
confirms behavior — for the symbol you are about to change, read its full body, and be
deliberate with behavior-critical code (the standards-sync digests and refusal paths,
scaffold output, packaging). Follow every Gortex hook instruction even when raw
`Read`/`Grep`/`Glob` remain callable. If the daemon does not yet track this checkout,
say so and fall back — do not start a daemon.

## Findings that outlive the session

**This applies to you, the main session, not only to subagents.** If a session produces
something **durable, non-obvious, and not recoverable from git, the PR, or the tracker** —
a measured number, a decision and why it beat the alternative, an honest negative, a
defect *pattern* rather than a defect, a trap that looks safe — append it to the memory
ledger:

```sh
node .claude/hooks/memory-propose.mjs <<'JSON'
{"concept":"short label","content":"the fact itself, self-contained, readable in a year","summary":"one line","type":"fact","tags":["sdk","…"],"source":"main"}
JSON
```

- **Tags carry `sdk` plus at least one descriptive tag.** `sdk` is this repository's
  identity in the shared `benchweave` vault and does not count toward the tag minimum on
  its own — the validator rejects `["sdk"]` alone, and that rejection is the rule working.
- **Review findings are exempt from the noise bar and are never optional:** every review —
  code-reviewer, RedTeam, adversarial audit, a human review relayed by an agent — appends
  its findings record (every severity including LOW and NIT, each with its disposition)
  before the session ends. Principal directive 2026-09-14.
- The bar for what merits a proposal, and the do-not-propose list:
  `.claude/memory-protocol.md`. The ledger is gitignored; no credentials, no client
  identifiers. Proposals drain into the `benchweave` vault on `PreCompact` / `SessionEnd`
  / a debounced `Stop`; `memory-freshness.mjs` reads the receipt at `SessionStart` and
  speaks up when the queue is stale. **codex sessions:** no drain hook fires there — run
  `node .claude/hooks/memory-drain.mjs --base http://127.0.0.1:8125/mcp` before ending a
  session that queued proposals.
- Sessions rooted in the **submodule mount** (`packages/sdk` inside the main checkout)
  fire no lifecycle hooks from this repository (their hooks resolve to the main
  checkout's settings): prefer proposing from a real checkout of this repository, or
  drain by hand (`.claude/memory-protocol.md` § Worktrees has the detail).
