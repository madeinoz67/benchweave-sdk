# BenchWeave plugin project — agent guide

This file is maintained by benchweave-sdk 0.6.0. The command
`benchweave-sdk upgrade` refreshes it. If you edit this file, the upgrade writes
conflict markers. Resolve both sides, then commit.

Claude Code loads this file through the import line `@AGENTS.md` in `CLAUDE.md`.
If your `CLAUDE.md` does not carry that line, add the line yourself. Projects
made before this file existed do not have it.

## Usage — the five steps

Do the five steps in order. Run every command from the directory that contains
`pyproject.toml`.

1. **Set up the environment.** Make a virtual environment. Install the project
   with `uv pip install -e '.[test]'`. Run `benchweave-sdk doctor`. `doctor`
   compares the SDK pin in `pyproject.toml` with the installed SDK. `doctor`
   reports a mismatch; it does not fail the run, and it works offline.
2. **Collect the facts.** Open `AI-GUIDE.md`. Use its five prompts one at a
   time: facts, implementation, demonstration, review, release. Give the AI
   the exact model, firmware, transport and protocol evidence.
3. **Run the checks.** Run `pytest`. Run
   `benchweave-sdk check src/example_plugin/descriptor.json`. The check
   validates the descriptor offline. The checks are partial; they do not cover
   all S01–S18, C01–C12 and M01–M14 obligations. If the project has
   presentation files, see `UI-GUIDE.md` for the UI checks.
4. **Get an independent review.** Prepare the exact revision, the descriptor
   and the evidence for a reviewer that did not write the code. Do not execute
   a hardware qualification plan without separate authority.
5. **Build and show the owner.** Run `uv build`. Run
   `benchweave-sdk inventory dist/` for the hash rows. Show the owner the built
   files, the evidence and the remaining gaps. Do not publish without the
   owner's approval.

## Keep the project current

Run `benchweave-sdk upgrade` on a committed and clean git tree. The upgrade
moves the managed files of this template. Your own files stay byte-identical.
A file that you and the template both changed gets conflict markers; resolve
both sides, then commit. Projects made before the copier port need
`benchweave-sdk adopt` first.

## Skills

The directory `.claude/skills/` holds five SDK-managed skills:

- `benchweave-plugin-workflow` — the five steps as commands.
- `benchweave-descriptor` — descriptor authoring and its refusal codes.
- `benchweave-plugin-ui` — offline UI checks and the simulated preview.
- `benchweave-adapter-testing` — adapter tests against SDK mocks.
- `benchweave-capture` — standalone capture without a gateway.

## Safety rails

- This project is synthetic. Do not contact hardware. Do not flash firmware.
  Do not energise outputs.
- Publish nothing without separate authority from the project owner.
- A preview success is not an admission. A check pass is not a hardware
  qualification.

## Documents

- `AI-GUIDE.md` — the five build-out prompts.
- `UI-GUIDE.md` — UI authoring; present in projects made with `--with-ui`.
- Rendered guide for this SDK version:
  https://madeinoz67.github.io/benchweave-sdk/docs/v/0.6.0/
- Guide source: `user_guide/plugin-sdk.qmd` in the benchweave-sdk repository.
