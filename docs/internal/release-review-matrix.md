# Release-review matrix — every surface a version bump can leave stale

> The instrument the release review walks, per issue #117. Each row is a
> version-bearing surface, the machine source that outranks it, and what stale
> looks like. Run the matrix between "code merged" and "tag pushed" — after the
> bump commit exists, before the tag is cut. Every row records its result
> (updated / correct-as-is / n-a), including empty results; an empty contributor
> window is a recorded result, not a skipped step.

| # | Surface | Machine truth | Stale pattern |
|---|---------|---------------|---------------|
| 1 | README version stamp (baseline line) | `pyproject.toml` `version` | previous release number |
| 2 | Website hero status line (`website/index.html`, hero badges) | `pyproject.toml` + `OTDP_VERSION` / `ADAPTER_API_VERSION` in `src/benchweave_sdk/__init__.py` | previous SDK number, OTDP number behind the constant |
| 3 | Website docs-version selector (options + `(latest)` label) | `great-docs.yml` `versions` list + git tags | previous `(latest)` label, missing prior-release option |
| 4 | Website compatibility tagline | `standards-lock.json` `compatibility.main_project` floor + the release's tested pair | previous SDK number against the gateway floor |
| 5 | Website standards badges (interface / plugin-ui / plugin-ui-preview) | `standards-lock.json` `standards[].version` per id | badge behind the vendored contract version |
| 6 | `great-docs.yml` `versions` list | git tags | new tag absent, previous release still `latest: true` |
| 7 | Contributor window | `git log <prev-tag>..HEAD --format='%an'` minus bots and the owner | unacknowledged new human contributors; empty window = recorded result |
| 8 | Gateway `uv.lock` SDK pin (cross-repo) | the released SDK version | pin behind the release; moves on the gateway's next gateway-side lock run — a note, not a blocker |

## The ordering constraint (row 6 is a pre-tag step)

The registration of the new version in `great-docs.yml` must land **before
the tag is cut**, not after: the docs assembly builds each version's bucket
from that version's own tag, and filters the tag's own versions list against
the requested version. A tag whose list does not contain itself builds zero
versions and fails (observed: v0.0.4 cut before its registration; the Build
Docs job failed with `Multi-version build: 0 version(s)` until the tag was
re-pointed onto the registration commit). v0.0.3 got this right by four
minutes; the review exists so the next release does not depend on luck.

## How the rows resolve

- Prose defers to the machine source in the middle column; when they disagree,
  fix the prose, never the machine source.
- Rows 1–6 are SDK-repo surfaces, edited in the release-review PR that also
  carries this matrix's result table. Row 7 runs `git log` against the two
  tags; row 8 is a recorded note unless the pin is materially misleading.
- Post-release verification (after the pipeline): PyPI JSON API shows the new
  version with wheel + sdist; the docs site shows the new bucket in the
  selector; the release body is the git-cliff notes.

## Lineage (why this exists)

Found by the v0.0.4 release review (issue #117): the README stamp was re-staled
by the very release that fixed it one release earlier, the website status line
carried an OTDP 0.1.0 vs machine-constant 0.2.0 drift nobody had caught, the
plugin-ui badge was two contract versions behind the lock, and the docs
selector lacked the prior-release option. Principal directives 2026-09-20:
the bump triggers a release review (docs sweep + contributor acknowledgment),
the checklist is a matrix in `docs/internal`, and a skill walks it.
