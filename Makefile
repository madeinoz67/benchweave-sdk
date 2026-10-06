.PHONY: release-cut

# One source of truth for uv's project environment (non-dot venv/, per the
# gateway Makefile's pin; := deliberately — an ambient value must not
# reintroduce a stray .venv/ on any target in this file).
export UV_PROJECT_ENVIRONMENT := venv

release-cut:
	uv run python scripts/release_cut.py $(VERSION)
