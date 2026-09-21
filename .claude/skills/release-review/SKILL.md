---
name: release-review
description: >-
  The release-review gate for benchweave-sdk. Use whenever a version is bumped
  or a release is being cut (trigger words: release, cut a release, version
  bump, tag, publish a version) — between "code merged" and "tag pushed".
  Walks the release-review matrix at docs/internal/release-review-matrix.md.
---

# release-review — nothing ships until the matrix is walked

A version bump is not one file. The bump commit changes `pyproject.toml`, but
the release only exists once every version-bearing surface agrees with it. This
gate runs after the bump commit exists and before the tag is cut.

## The gate

1. **Walk the matrix.** Open `docs/internal/release-review-matrix.md` and walk
   all 8 rows. Each row: check the surface against its machine source, fix the
   prose where stale, and record the result (updated / correct-as-is / n-a).
   Every row records a result, including empty results; an empty contributor
   window is a recorded result, not a skipped step.
2. **Registration precedes the tag.** Row 6 lands before the tag is cut:
   the docs assembly builds each bucket from the version's own tag and reads
   that tag's own versions list, so a tag missing itself fails the build.
3. **Prose defers to machine truth.** The matrix's middle column names the
   machine source per row. When prose and machine disagree, the prose is wrong.
   Never edit the machine source to match prose.
4. **Contributor acknowledgment.** Row 7 is not optional: run the git log, and
   acknowledge new human contributors in the release notes. If the window is
   empty, record that as the result. The acknowledgment must land in the
   RENDERED release notes and CHANGELOG.md — the cliff template renders a
   Contributors section with @mentions (GITHUB_TOKEN wired in publish.yml);
   the tag message is the permanent record, never the only home. If the
   rendered notes somehow lack the section (template regression, token
   missing), append it to the release body by hand before the review closes.
5. **Release notes / tag message** are composed in the principal's voice via
   the `stephens-digital-twin` skill (GitHub-facing prose directive). The
   publish pipeline replaces the GitHub release body with git-cliff notes; the
   tag message is the permanent record.
6. **Post-release verification** (after the pipeline runs): PyPI JSON API shows
   the new version with wheel + sdist; the docs site selector shows the new
   bucket; the release body is the git-cliff notes. Appearance is not
   existence: read PyPI, do not infer from pipeline status alone.

## Scope

SDK-repo surfaces. Row 8 (gateway `uv.lock`) is a recorded note, not a
blocker. The gateway can adopt this skill/matrix pair when its own releases
need the same gate.
