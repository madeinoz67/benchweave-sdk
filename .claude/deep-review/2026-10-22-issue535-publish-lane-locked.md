# Design — issue #535: make the publish lane honour the lock

Date: 2026-10-22 · Repo: benchweave-sdk · Branch: `fix/issue535-publish-lane-locked` (off `origin/main` @ `ce7c01f`) · Tracker: gateway #535 (single issue stream; SDK-side work)

**Verdict: BUILD.** One line changes and one mechanism moves: the release build's
environment setup goes from a resolving sync to a verifying one. The audit's stated
reproduction does not reproduce (§1.4) and is not claimed here; the hole this closes is a
different one, measured in §6.

## 1. The verified problem

Read from the tree at `origin/main` (`3fa10c7`, released as v0.18.0):

1. `.github/workflows/publish.yml:29` — `- run: uv sync`. This is the only environment
   setup the job that builds the wheel performs. The job then runs
   `uv run benchweave-sdk sync-standards --check` and `uv build`.
2. The two continuous-integration syncs are already locked: `ci.yml:49` —
   `uv sync --locked --extra test --extra server --extra scaffold`; `ci.yml:227` —
   `uv sync --locked --extra test --extra server`. The release is therefore the one lane
   in this pipeline whose environment never verifies the lock.
3. `pyproject.toml:2` — `requires = ["hatchling>=1.26"]`. A lower bound with no upper
   bound, and `hatchling` appears nowhere in `uv.lock`: the build backend is resolved
   fresh from the package index at release time, whatever the lock says. Deferred (D1);
   this slice does not touch it.
4. **The audit's stated reproduction does not reproduce.** Editing a version inside
   `uv.lock` (leaving the artifact's own metadata alone) makes uv refuse in BOTH modes
   with a wheel-filename consistency error — a corrupt lock, exit 2, identical under
   `uv sync` and `uv sync --locked`. It is not a drift-detection difference, and this
   record does not claim it.
5. **The real hole is project-metadata ↔ lock drift.** When `pyproject.toml` and
   `uv.lock` disagree, a bare `uv sync` exits 0 and silently rewrites `uv.lock`. A
   release can then be built and smoke-tested against a resolution no pull-request lane
   ever ran, and nothing fails. With `--locked`, the same tree exits 1 with an actionable
   error. §6 proves both halves on a scratch copy.

## 2. The slice

One line in the publish build job:

| | line |
|---|---|
| before | `      - run: uv sync` |
| after | `      - run: uv sync --locked` |

Nothing else moves: no job added or removed, no trigger change, no step reordered, no
change to the smoke, publish, tap or changelog jobs.

**Why `--locked` and not the CI jobs' extras.** The precedent those two jobs set is the
`--locked` flag. They disagree on extras (`--extra test --extra server --extra scaffold`
at `ci.yml:49`; `--extra test --extra server` at `ci.yml:227`), which shows the extras are
per-job selection rather than the shared posture. The publish build job's two
environment-using steps need the base install (`sync-standards --check`) and an isolated
build environment (`uv build`) — neither needs an extra. Installing the test, server or
scaffold extras at release time would widen the release's dependency surface for no proof
the lock flag does not already give. §6 arm A3 tests that a bare-`--locked` sync still
refuses drift anywhere in the metadata, including in an extra it did not request.

**The steps after the sync cannot paper over drift.** `uv run` can refresh the
environment, but by the time it runs the sync has already refused any tree whose lock
disagrees with the metadata. A successful `uv sync --locked` is the statement that the
lock is current; nothing later in the job can re-resolve around that.

**The smoke lane keeps resolving freshly from the index — deliberately.** The smoke job
takes the built wheel and installs it into a throwaway venv
(`uv pip install --python … "${WHEEL}[scaffold]"`); no project lock is in play. That is
the user-facing contract: the *published wheel* installs cleanly on a machine that has
never seen this repository. Locking that install would replace the contract with "our own
lock resolves", a weaker and different claim. Left alone.

## 3. Precedent

- `ci.yml:49` and `ci.yml:227` — the two lanes already treat `--locked` as the posture
  for environment setup. This applies the existing posture to the third lane instead of
  inventing one.
- `scripts/release_cut.py:620` already treats a red `uv sync --locked` as an
  environment-refresh failure (`env_refresh_failed:`), so the release tooling assumes a
  locked environment everywhere except the workflow that builds the release.
- No new architecture, no new tool, no new file.

## 4. Invariant and drift impacts

- **Hard invariants (STD/PKG): none touched, none gained.** The change is a workflow
  line. It does not touch `standards-lock.json`, the vendored tree, `hatch_build.py`, a
  refusal prefix, the scaffold, the conformance modules, or `pyproject.toml`/`uv.lock`.
  PKG-1 (self-containment) is unaffected: `--locked` reads the committed lock, which is
  in-repo.
- **Surfaces that move:** `.github/workflows/publish.yml` (one line) and this record. No
  source, test, docs-site, or version surface.
- **Drift obligations:** `docs/internal/drift-and-obligations.md` has no row naming
  publish's sync line. Its CI-map row for `publish` ("release integrity — tag, wheel,
  stamp verification") stays true and gains the lock check. Row 4 (packaging) is
  unaffected — no packaging bytes move.
- **Release review:** no version-bearing surface moves, so no release-review matrix row
  is in scope for this increment.
- **CI cost:** zero on pull requests (publish runs at release only); at release,
  `--locked` adds lock validation to a sync the job already runs.

## 5. Deferrals — each with its home and reopen trigger

| # | Deferral | Home | Reopen trigger |
|---|---|---|---|
| D1 | The build backend's own unbounded resolution: `hatchling>=1.26` is not in `uv.lock`, so the backend is fetched from the index at release time and can differ from what any lane ran. A later slice should constrain it with a build-dependency selector. Verified locally: `uv 0.12.12` supports `uv build --build-constraints <requirements file>` (env `UV_BUILD_CONSTRAINT`), which constrains the build environment's distributions. The release that *introduced* the flag was not established in this pass — name it before the slice lands. | This record, deferral D1 (documentation home; the carrier is unscheduled, so no issue). | Reopen when a release's wheel differs from what the pull-request lane's build produced, when `hatchling` majors, or when the SDK adopts a build-backend pin policy. The candidate mechanism and the verified tool version are named here so the slice starts from evidence. |
| D2 | A stale documentation row: the gateway's obligations table carries a `release-preflight` row describing a job no workflow defines. The identical row is ALSO present in this repository's copy at `docs/internal/drift-and-obligations.md:110`; no `.github/workflows/*` file defines such a job. A stale documentation row, not a missing job. | Separate documentation fix, its own gateway issue (named at filing time; not this increment's). | Reopen when either repository's CI map is next edited. |

## 6. Acceptance rule — pre-committed before any measurement ran

Substrate: a scratch copy of the tree created with `git archive HEAD | tar -x -C <dir>`,
outside both repositories. No real corpus, no names. Exit codes are read from the command
itself (no pipes, no summary lines). Lock state is compared by the sha256 of `uv.lock`
before and after.

**A1 — bare sync hides the drift (RED).** In the scratch copy, add one dependency to
`[project].dependencies` that `uv.lock` does not contain. Run the current pipeline line,
`uv sync`.
PASS = exit 0 **and** `uv.lock`'s sha256 changed (the lock was rewritten).

**A2 — the lock flag refuses the same drift (GREEN).** Restore the lock to its HEAD
bytes, keep the same metadata drift. Run `uv sync --locked`.
PASS = exit non-zero **and** the message names the lock or instructs how to update it
**and** the lock's sha256 is unchanged.

**A3 — the extras are not needed for coverage.** Restore the lock; move the drift only
into `[project.optional-dependencies].server`. Run `uv sync --locked` **with no extras**.
PASS = exit non-zero. If it exits 0, the design fork is real: `--locked` does not
validate unrequested extras, so the slice must request the extras whose metadata can
drift (or use `--all-extras`). Report that result and re-decide; do not widen silently.

**A4 — the changed line is what runs.** In a fresh scratch copy of the branch tree, run
the exact text now in `publish.yml` (`uv sync --locked`), then the job's own next two
commands (`uv run benchweave-sdk sync-standards --check`, `uv build`).
PASS = all three exit 0.

**A5 — RED control on the changed line.** In the scratch copy, revert only the workflow
line to `uv sync`, re-apply A1's drift, and run the line as written.
PASS = exit 0 (the drift passes silently through the old line). The A5/A4 pair is the
proof that the flag is the mechanism.

**STOP rule.** If A1 or A2 fails its PASS condition, stop and report: the mechanism is
not what this design says, and the slice needs rethinking, not a workaround. A3's failure
is a design fork to report, not a workaround either.

**Local gates after the change (the SDK's own lanes).** With
`UV_PROJECT_ENVIRONMENT=venv`: `uv run ruff check .`, `uv run mypy`,
`uv run benchweave-sdk sync-standards --check`, `python3
scripts/count_version_literals.py`, `uv run benchweave-sdk --version`, then the suite
`uv run pytest -q -m "not browser and not timing" -n auto` and `uv run pytest -q -m
timing`. Exit codes read directly; counts from the run, never from a summary line.

**What only a real release can prove — and therefore what this increment does NOT
claim.**

- That GitHub Actions executes the workflow as written: the checkout at the tag ref, the
  runner image, the action SHAs, the runner's own uv version, Trusted Publishing, and the
  PyPI upload.
- That the wheel built there is the wheel the smoke matrix installs on five operating
  systems and the file PyPI serves.
- That the unbounded `hatchling` build-backend resolution (D1) produces the same wheel
  locally and on the runner.

This record claims one thing: on the metadata-drift input, the release lane's environment
setup now refuses where it used to silently re-resolve.

## 7. Top risks

- **R1 The flag blocks a legitimate release.** If a tag carries metadata that differs
  from the committed lock (an operator edits `pyproject.toml` at tag time), the build now
  fails. That is the intended behavior — such a release is exactly the case this closes —
  but the failure must be actionable. Falsifier: A2 shows the message names the lock and
  the way to update it.
- **R2 No test pins the line.** The guard is the workflow itself plus this record; a
  later edit could reintroduce a resolving sync with no red lane. Disclosed residual. A
  YAML-string tripwire was considered and rejected: it pins a line, not a behavior, and
  the `increment` skill scopes a one-line mechanical edit outside the design/build/test
  loop. The scratch A4/A5 pair is the evidence this increment carries.
- **R3 Extra-only drift goes unvalidated.** A3 decides it; if it passes, the "no extras"
  call stands on evidence rather than assumption.
- **R4 uv semantic drift on the runner.** The runner installs uv through the pinned
  `setup-uv` action; `--locked` behavior could change between uv releases. Falsifier: A4
  runs the flag on uv 0.12.12 locally; the runner's version is only proven by a release
  (named in §6's not-claimed list).

## 8. Issue disposition

- **#535**: this increment's tracker; closes on merge of the SDK pull request.
- **D1**: deferred as above (no issue; unscheduled carrier).
- **D2**: deferred to a separate documentation fix; the stale row exists in this
  repository's copy as well as the gateway's.

---

## Addendum 2026-10-22 (post-measurement) — the smoke-lane decision and the PR-time twin

Two points established after the record above was committed and measured. This addendum
changes no mechanism and no acceptance rule; §6's rule and its results stand as written.

**The smoke lane's fresh resolution is a decision, not an omission.** The wheel's declared
dependencies ARE the user-facing contract, and its load-bearing pins are already exact
(`benchweave-ui-html==0.3.1` and `fastmcp==4.1.0` in the `[server]` extra). A user installs
the published wheel from an index and receives the resolution of that metadata — not this
repository's lock. Locking the smoke install would therefore test an install no user gets,
and it would mask upper-bound breakage that the published metadata permits and the lock
happens to hide. §2's "left alone" is this decision.

**The in-tree philosophy this follows.** `ci.yml`'s installed-wheel smoke step is titled
"(the publish workflow's block, at PR time)" and its comment says the publish smoke runs
only at release, so the same commands run on every OS in the pull-request matrix — "every
release-time arm has a PR-time twin." This change preserves that shape: the release's
locked sync is the same `--locked` posture every pull-request lane already runs, so the
release-time arm is a twin of the PR-time one, not a new release-only mechanism.
