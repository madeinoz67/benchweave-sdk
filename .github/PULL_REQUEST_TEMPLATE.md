## What

<!-- One or two sentences: what does this PR change? -->

## Why

<!-- The problem or motivation. Link issues as `Fixes #123`. -->

## Gates

All run locally before review:

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy src`
- [ ] `uv run benchweave-sdk sync-standards --check`
- [ ] `uv build`

- [ ] Every deferral named in this PR body cites an open issue — orphan deferrals
      block merge (main #69).

## Notes for reviewers

<!-- Anything non-obvious: design trade-offs, follow-ups, evidence pointers. -->
