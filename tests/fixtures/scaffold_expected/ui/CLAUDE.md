# Agent notes for this plugin project

Project: synthetic BenchWeave device plugin (package `example_plugin`). This
file is developer tooling at the repository root: it never enters the wheel
(`packages = ["src/example_plugin"]`), and if a release ever ships it, the
registry manifest catalogues it as `documentation`, not `skill`.

## Commands

- Run the tests: `pytest`
- Validate the descriptor offline: `benchweave-sdk check src/example_plugin/descriptor.json`
- Build the wheel and sdist: `uv build`
- Pin dependencies: `uv lock`

## Where things are

- `AI-GUIDE.md` — the five build-out prompts (facts, implementation,
  demonstration, review, release)
- `src/example_plugin/skills/` — the seeded agent skills:
  `develop-plugin/SKILL.md` (authoring workflow, elicitation questions,
  release mechanics) and `drive-device/SKILL.md` (the synthetic demo
  driver; rewrite it for the real device)
- `src/example_plugin/descriptor.json` — the OTDP descriptor under check

## Safety rails

This project is synthetic: do not contact hardware, flash firmware or
energise outputs while authoring plugin code, and publish nothing without
separate authority from the project owner.
