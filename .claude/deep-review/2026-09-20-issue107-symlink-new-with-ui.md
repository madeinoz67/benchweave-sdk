# Issue #107 — `new --with-ui` under symlinked destinations: resolve-before-write plus a typed symlink refusal

- Date: 2026-09-20
- Status: design (pre-implementation; this record precedes the fix commit on `fix/issue107-symlink-with-ui`)
- References: gateway issue #107 (`madeinoz67/benchweave#107`, single-issue-stream rule), SDK base `51bf053`
- Severity: LOW (functional CLI defect, no conformance or security impact)

## 1. Root cause — verified in the code, not assumed

`read_file` in `src/benchweave_sdk/presentation.py` walks every path component with
`O_NOFOLLOW`:

```python
parts = path.absolute().parts
directory = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)
try:
    for part in parts[1:-1]:
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        os.close(directory)
        directory = child
    descriptor = os.open(
        parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
```

`Path.absolute()` does **not** resolve symlinks. On macOS `/tmp` is a symlink to
`private/tmp`, so for `/tmp/<proj>/src/<pkg>/descriptor.json` the walk opens `tmp` with
`O_DIRECTORY | O_NOFOLLOW`; refusing to follow leaves a symlink where a directory was
demanded, and macOS reports **ENOTDIR** (`[Errno 20] Not a directory: 'tmp'`). Linux
reports ELOOP for the same shape — different errno, same strictness. This is the
mechanism the issue states, and it is confirmed by the code.

The failure lands mid-scaffold. `cli.py` `new_command`:

```python
create_project(directory, package_name)
if with_ui:
    from .presentation import create_ui_resources
    create_ui_resources(directory, package_name)
```

and `create_ui_resources` reads back the descriptor the scaffold just wrote:

```python
root = destination / "src" / package
raw = read_file(root / "descriptor.json")
```

So `create_project` has already written the full base tree when the walk dies on the
`tmp` component: **half-generated project** (base scaffold present; `presentation.json`,
`binding-catalogue.json`, `ui/`, `UI-GUIDE.md`, `tests/test_presentation_preview.py`
absent). `_domain_errors` converts the `OSError` into `click.ClickException(str(exc))`,
so the user sees bare errno prose — no `snake_case:` prefix, no hint toward
`/private/tmp`. Both halves of the issue are real.

Scope facts established from the code:

- **Plain `new` cannot fail this way.** `create_project` validates the package name and
  the descriptor *before* `destination.mkdir(parents=True, exist_ok=False)`, and writes
  via plain `pathlib` (symlink-following, no `read_file`). `read_file` is reached only
  under `--with-ui`. The defect is exclusive to `new --with-ui` (and, separately, the
  check/preview lanes refuse symlinked ancestors *by design* — that contract stays).
- **`create_ui_resources` already has internal atomicity discipline** — its comment:
  "Validate everything derivable before the first write so a rejected descriptor leaves
  no half-generated project behind", pinned main-side by
  `test_create_ui_resources_is_atomic_on_unusable_descriptors`. The gap is not inside
  `create_ui_resources`; it is that its *first read* can fail on the destination's
  ancestors **after `create_project` already wrote the tree**.
- **No test pins the raw errno text.** `test_ui_check_rejects_symlinked_resource`
  (main-side `tests/sdk/test_presentation_cli.py`) pins only exit code 1 for a symlinked
  manifest. Converting the exception to a prefixed `ValueError` changes message text
  only; `_domain_errors` catches `ValueError` and `OSError` identically.

## 2. Mechanism

Two coordinated, minimal changes. (M1/M2' as briefed, confirmed by the code with two
corrections: the ENOTDIR disambiguation must be explicit, and the final component
deserves the same refusal.)

### M1 — `new` resolves the destination before any write (`cli.py`)

In `new_command`, before `create_project`:

```python
destination = directory.expanduser().resolve()
```

and use `destination` for `create_project`, `create_ui_resources`, and the completion
message. Effects:

- `/tmp/<proj>` resolves to `/private/tmp/<proj>` on macOS; every component the walk
  opens then exists literally, and `create_ui_resources`' `read_file` cannot fail on an
  ancestor. `resolve()` (non-strict) handles not-yet-existing tails.
- This **is** the half-tree fix: the only known post-write failure path in
  `new --with-ui` is removed before the first write. `resolve()` performs no writes, so
  adding it cannot create a new half-tree path; the existing pre-write refusals
  (reserved package name, invalid descriptor, existing destination) keep firing first
  inside `create_project` exactly as today.
- `expanduser()` is a one-call rider: today `new ~/x` creates a literal `~` directory in
  the working directory (Click does not expand), which would then also defeat the strict
  walk under `--with-ui`. Included in M1; flagged here so the reviewer sees it is a
  deliberate rider, not scope creep.
- Uniform for plain `new` and `--with-ui`. Observable difference for non-canonical
  inputs: the project is created at the real path and the success message prints the
  canonical path. No test pins the old message.

### M2' — `read_file` stays strict; symlink-shaped errors become a prefixed refusal (`presentation.py`)

The walk keeps `O_NOFOLLOW` on every component — **no wholesale `Path.resolve()` inside
`read_file`**: resolving there would silently follow *internal* symlinks (an
`ui/presets/x.json → /etc/passwd` tree would pass check-ui against a non-canonical
project), defeating the strictness that `test_ui_check_rejects_symlinked_resource` and
the README contract ("resource paths … cannot traverse symlinks") pin. The strictness is
the feature; only the *error shape* changes.

Wrap each component open (directory components and the final component). On `OSError`
with errno `ELOOP` or `ENOTDIR`, confirm the component really is a symlink before
claiming it:

```python
except OSError as exc:
    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
        try:
            metadata = os.stat(part, dir_fd=directory, follow_symlinks=False)
        except OSError:
            raise exc from None          # confirmation failed: never mask the original
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(
                f"path_symlink_component: {part}: canonical paths only, no symlink "
                "components (on macOS use /private/tmp rather than /tmp)"
            ) from exc
    raise                                # genuine ENOTDIR / EACCES / anything else: unchanged
```

The `ENOTDIR` disambiguation matters because a regular file mid-path (for example
`check a/b.json` where `a` is a file) is *also* ENOTDIR and must keep today's raw error.
Other errnos (`EACCES`, `ENOENT`, …) propagate unchanged. New import: `errno`.

Expected observables after both changes:

- `new --with-ui <symlinked destination>` exits 0 with a complete tree at the real path.
- `check` / `check-ui` / `check-preset` / `preview-ui` under a symlinked ancestor still
  refuse (exit 1 — contract preserved) but with `path_symlink_component: …` instead of
  raw errno prose.
- A symlinked final resource (the existing test's shape) also now reports the prefix;
  exit stays 1.

## 3. Half-tree policy ruling

**Pre-flight (M1) — chosen. Cleanup-on-failure — rejected.** Reasons: the only live
post-write failure in `new --with-ui` is the ancestor walk, and M1 removes it before the
first write; `create_project`'s own refusals already fire before any write; a
cleanup-on-error path (`shutil.rmtree` of a half tree on exception) deletes user-visible
trees on any future error and adds a failure mode rather than removing one. Honest
residual (stated, not guarded): a disk-full or permission error *during* the write phases
of `create_project` or `create_ui_resources` can still leave a partial tree — true today,
unchanged by this increment, out of scope at LOW severity.

## 4. Minimal first increment

**SDK repo (branch `fix/issue107-symlink-with-ui`, base `51bf053`):**

1. Commit 1 — this design record (design-record-first).
2. Commit 2 — the fix:
   - `src/benchweave_sdk/cli.py`: `new_command` resolves the destination (M1).
   - `src/benchweave_sdk/presentation.py`: `read_file` typed refusal (M2'), `import errno`.
   - No other files. No scaffold-template bytes change. No vendored/lock bytes change.

**Main repo (gateway checkout, separate commit/PR after the SDK PR merges — TWO-1):**

3. New tests in `tests/sdk/test_presentation_cli.py` (the module that already owns
   scaffold/UI CLI behavior and pins `create_ui_resources` atomicity):
   - `test_new_with_ui_succeeds_under_symlinked_ancestor` — creates its own symlinked
     ancestor (do **not** rely on `tmp_path` being symlinked; on macOS it is already
     canonical): `real = tmp_path / "real"`, `link = tmp_path / "link"`,
     `link.symlink_to(real)`, then `run("new", link / "proj", "--with-ui")`; asserts
     exit 0 and the complete UI tree (`presentation.json`, `binding-catalogue.json`,
     `ui/manifest.json`, `ui/fixtures/normal.json`, `UI-GUIDE.md`,
     `tests/test_presentation_preview.py`), and — the SRF-1 control — byte-compares every
     generated file against a twin scaffolded through a canonical path with the same
     package.
   - `test_check_ui_refuses_symlinked_ancestor_with_prefix` — scaffolds `--with-ui` into
     a real tree, runs `check-ui` with the envelope/resources arguments routed through a
     symlinked ancestor; asserts exit 1 **and** `path_symlink_component:` in output
     (the prefix assertion is what makes this test RED — the exit code alone is not).
   - `test_read_file_propagates_genuine_not_directory` — a regular file mid-path keeps
     raising the raw `OSError` (no prefix). This is a guard, expected GREEN at base —
     it pins the disambiguation clause "other errnos propagate unchanged".
4. Submodule pointer bump to the SDK merge SHA in the same gateway PR.

**How the proving runs resolve the code (verified):** the module's autouse `sdk_source`
fixture does `monkeypatch.syspath_prepend(<gateway-checkout>/packages/sdk/src)`, so the
suite imports `benchweave_sdk` from the **submodule working tree**, not from the venv's
installed copy. RED therefore requires the submodule checked out at `51bf053`
(pre-fix); GREEN at the fix branch/merge SHA. The venv only supplies the SDK's runtime
deps (click, rich, textual, jsonschema). Run:
`UV_PROJECT_ENVIRONMENT=venv uv run pytest tests/sdk/test_presentation_cli.py -q` from
the gateway checkout root, plus the full `tests/sdk` suite before landing.

**Docs (obligation 1 — CLI-visible behavior):** README "Path resolution and validation"
keeps the check/preview guidance verbatim (it stays true); add one sentence in the
directory-structure section stating that `new` accepts symlinked destinations by
canonicalizing them and prints the real path. `user_guide/plugin-sdk.qmd` §1 ("The SDK
creates missing parent directories and refuses to overwrite an existing project.")
gains the same clause. Do **not** change the `/private/tmp` prose to promise resolution
in the check/preview lanes — they keep refusing.

**Deferrals (explicit):**

- Consistency treatment for `inventory`'s directory argument (`packaging.py` has its own
  symlink rejection) — not touched; file only if a user hits it.
- Windows portability of the `dir_fd` walk — pre-existing posture (`read_file` already
  uses `dir_fd` unconditionally; SDK CI is ubuntu-only and my change adds `dir_fd`-based
  calls only on an already-unreachable error path). No new Windows exposure.
- `docs/internal/invariants.md` STD-4 prefix enumeration stays as-is — it enumerates the
  sync lane; presentation-lane prefixes (`preview_*`) are not enumerated there either;
  adding one name is possible but not required by the invariant's text ("every refusal
  path raises a `snake_case:`-prefixed `ValueError`"), which this change satisfies.
- Write-phase partial-tree hardening (disk-full) — named as residual above.

## 5. Invariant impacts

- **STD-4**: one new refusal prefix `path_symlink_component:` joining the
  machine-matchable family. Precedent: the presentation lane's existing
  `preview_unsupported_parameter_type:`, `preview_invalid_presentation:`,
  `preview_fixtures_directory_expected:`, `preview_renderer_origin_not_local:`.
  Errno-family `OSError`s that are *not* symlink-shaped deliberately keep today's shape.
- **SRF-1**: generated output byte-identical — the fix changes where/whether writes
  happen, never what is written. Pinned by the byte-compare control inside the new
  scaffold test; `test_optional_ui_preserves_descriptor_and_adapter` continues to hold.
- **SRF-2**: preview and check-ui share `read_file`; both gain the same refusal shape —
  agreement preserved, not weakened.
- **STD-1/2/3/5, PKG-1/2/3**: untouched — no vendored bytes, no lock, no packaging, no
  parent-checkout reads. `sync-standards --check` unchanged. **Not a Tier-3 review**
  (no standards tree or lock involvement).
- **TWO-1**: sequencing in §4 (SDK commit pushed first; gateway pointer + tests second;
  SDK PR body carries `Fixes madeinoz67/benchweave#107` and notes no SDK-side issue
  exists by design — retired tracker).

CI cost: zero new jobs; three tests in an existing module, seconds of runtime.

## 6. Measurable proof — pre-committed acceptance rule

Written before any run of the new tests (this document is committed on the branch before
the fix commit; that ordering is the proof of pre-commitment).

**State the expected numbers first:**

- Current module count: 8 test functions in `tests/sdk/test_presentation_cli.py`; after:
  11. Any other count means the wrong module or a lost test.
- Manual repro at `51bf053` on macOS, `UV_PROJECT_ENVIRONMENT=venv uv run
  benchweave-sdk new --with-ui /tmp/<fresh>-plugin` (single positional DIRECTORY;
  controller-verified 2026-09-20 — the CLI takes one positional, default package
  `example_plugin`): exit 1; stderr contains
  `Not a directory`; tree state: `src/example_plugin/descriptor.json` present,
  `src/example_plugin/presentation.json` and `UI-GUIDE.md` absent.
- With the fix, the identical command: exit 0; complete tree at `/private/tmp/<fresh>-plugin`.

**RED (submodule at `51bf053`, new tests present):**

- `test_new_with_ui_succeeds_under_symlinked_ancestor` FAILS with the scaffold assertion
  (exit 1 / missing `presentation.json`) — not an import or collection error
  (`--collect-only` must show the 3 new tests; `no tests ran` = the RED check FAILED).
- `test_check_ui_refuses_symlinked_ancestor_with_prefix` FAILS on the prefix assertion
  (exit code is already 1 at base — only the message assertion goes red).
- `test_read_file_propagates_genuine_not_directory` PASSES (guard, not a RED test).

**GREEN (fix applied — via `cp` backup/restore for local re-proving, never
`git checkout` over uncommitted work; via submodule SHA in the gateway tree):**

- All 11 module tests pass; full `tests/sdk` suite green; SDK gates clean
  (`uv run ruff check .`, `uv run mypy` — bare, agreeing with CI's `uv run mypy src` —
  `uv run benchweave-sdk sync-standards --check`, `uv run benchweave-sdk --version`);
  SDK release smoke (`uv run pytest -q`) green.

**Both kill directions:**

- **Ship** iff: RED reproduces exactly as specified above AND GREEN is clean AND the
  byte-compare control shows zero differences.
- **Kill** if: `test_new_with_ui_succeeds_under_symlinked_ancestor` passes at `51bf053`
  — the defect is not real in the harness (environment difference); do not build, report
  instead.
- **Kill/adjust** if: the prefix assertion is already green at base — that would mean the
  lane already carried the contract (contradicted by the code read; treat as an
  underpowered measurement — the wrong assertion is being tested — not as a pass).
- **Underpowered, not conclusive:** if symlink creation in the test errors (rather than
  fails) in a lane where the module runs — that lane never had the defect. Follow module
  precedent (`test_ui_check_rejects_symlinked_resource` is ungated); do not add
  platform gating.

## 7. Top risks

1. **The ENOTDIR disambiguation misfires** (a genuine file mid-path gets the symlink
   prefix, or a race between `open` and the confirming `stat` masks a real error).
   Mitigated by the lstat confirmation with re-raise-on-confirmation-failure;
   falsified by `test_read_file_propagates_genuine_not_directory`.
2. **Canonical-path observables surprise a user** who expected the project at the
   symbolic path (message now prints the real path). No test or doc pins the old
   message; README/user-guide sentences added in this increment disclose it.
   Falsified by: any test asserting the old literal message path (none found).
3. **A CI lane without symlink privilege** errors on the new tests. Precedent: the
   module's existing symlink test is ungated and passes where the suite runs; SDK CI is
   ubuntu-only, main-side suite unchanged in lanes. If an existing lane breaks, that is
   a finding, not a reason to gate the test.

## 8. DON'T-BUILD check

Not triggered. The defect is confirmed in code (walk + `absolute()` + write-then-read
ordering), the mechanism closes it before the first write, and the proof is a binary
exit-code/tree-shape control plus a byte-identity control — not fluff. Severity LOW is
respected by a two-function, zero-dependency change.
