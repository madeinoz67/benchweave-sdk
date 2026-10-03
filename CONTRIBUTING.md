# Contributing to benchweave-sdk

Thanks for your interest in a contribution. This project follows the
[Contributor Covenant](CODE_OF_CONDUCT.md). If you participate, you agree to
uphold it.

This repository is the SDK for [BenchWeave](https://github.com/madeinoz67/benchweave).
It lives in the main repository as `packages/sdk`. The project publishes it to PyPI
from here. It has its own CI.

## Getting set up

- Python 3.13+ with [uv](https://docs.astral.sh/uv/).
- This repo keeps a non-dot `venv/`. Keep uv pointed at it so that uv does not
  create a stray `.venv/`:

  ```sh
  UV_PROJECT_ENVIRONMENT=venv uv sync
  ```

## Before you open a PR

All gates must pass locally. Use the same commands that CI runs:

```sh
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run benchweave-sdk sync-standards --check
uv lock --check
uv build
```

CI syncs with `--locked`, and `uv.lock` records this package's own version.
A version bump or a dependency change needs `uv lock` in the same commit.
Otherwise the sync step fails.

Bug fixes ship test-first. A failing test that reproduces the bug lands in
the same change as the fix.

## Workflow

- Work on a feature branch. The `main` branch receives merges via pull request
  only.
- Use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, …). git-cliff
  generates the changelog from them.
- Keep commits small. Each commit carries one logical change.

## Reporting bugs

Open an issue with the SDK version, your Python version, and a minimal
reproduction. For security issues, follow [SECURITY.md](SECURITY.md). Do not
use a public issue for them.
