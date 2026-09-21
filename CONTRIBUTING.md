# Contributing to benchweave-sdk

Thanks for considering a contribution. This project follows the
[Contributor Covenant](CODE_OF_CONDUCT.md); by participating you agree to
uphold it.

This repository is the SDK for [BenchWeave](https://github.com/madeinoz67/benchweave)
and lives in the main repository as `packages/sdk` — it is published to PyPI
from here and has its own CI.

## Getting set up

- Python 3.13+ with [uv](https://docs.astral.sh/uv/).
- This repo keeps a non-dot `venv/`; keep uv pointed at it so it does not
  create a stray `.venv/`:

  ```sh
  UV_PROJECT_ENVIRONMENT=venv uv sync
  ```

## Before you open a PR

All gates must pass locally — the same commands CI runs:

```sh
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run benchweave-sdk sync-standards --check
uv lock --check
uv build
```

CI syncs with `--locked`, and `uv.lock` records this package's own version: a version bump
or a dependency change needs `uv lock` in the same commit, or the sync step fails.

Bug fixes ship test-first: a failing test that reproduces the bug lands in
the same change as the fix.

## Workflow

- Work on a feature branch; `main` only receives merges via pull request.
- Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, …) — the
  changelog is generated from them by git-cliff.
- Keep commits small — one logical change each.

## Reporting bugs

Open an issue with the SDK version, your Python version, and a minimal
reproduction. Security issues follow [SECURITY.md](SECURITY.md) — never an issue.
