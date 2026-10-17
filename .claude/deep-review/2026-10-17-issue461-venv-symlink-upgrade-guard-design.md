# L7 — issue #461: the upgrade walk and the LF rewrite leave the project's content boundary

- **Issue**: gateway #461 (`plugin SDK: upgrade writes conflict markers into the project virtual environment`), slotted L7 of the classref train (program record §7A / §8 row RC-7, `2026-10-14-classref-logic-analyser-design.md`).
- **Slice branch**: `design/l7-issue461-venv-upgrade-guard` (this record is its first commit).
- **Status**: DESIGNED — no implementation code written in this pass.
- **Evidence base**: `src/benchweave_sdk/scaffold_update.py` and `src/benchweave_sdk/scaffold.py` at `origin/main` `908acce` (post-L6); `tests/test_scaffold_update.py` lane at the same commit; gateway issue #461 body (SDK 0.12.0 upgrading from 0.10.0); the L6 record `2026-10-17-issue460-ui-contract-migration-design.md` §3 (#461 adjacency) and §7 (not-in-scope-by-construction).
- **Pre-flight (#181 R2)**: `git fetch origin` run. No unmerged remote branch's diff touches `scaffold*`, `upgrade*`, or `cli` (checked every `--no-merged` branch's name-diff). Open PRs: **none** on `madeinoz67/benchweave-sdk` and **none** on `madeinoz67/benchweave`. Recent merges on both are dependabot plus the L6 #172 / row12 arms — none overlap this surface. **Verdict: clean to design; no rival work.**

---

## 0. What actually happened — root cause against the source, with the report's attribution corrected

The issue names two defects and attributes the interpreter damage to "the conflict-marker write". Against the source, the actors are three, and the write is not the conflict-marker report:

1. **The walk enters ignored trees.** `_project_files` (`scaffold_update.py:45-50`) is `project.rglob("*")` filtered only by `".git" not in parts`. A gitignored `venv/` is walked in full. This function feeds both the pre-update snapshot (`_protected_snapshot`, :86) and the post-update conflict scan (:246-250) — both **read-only**.
2. **The conflict-marker notices on `venv/` files are false positives of that scan.** The scan flags any file whose bytes contain `<<<<<<<`. The OLD SDK installed in the project's venv carries our own constant `_CONFLICT_MARKER = b"<<<<<<<"` (`scaffold_update.py:29`) — so `venv/lib/.../benchweave_sdk/scaffold_update.py` flags on the SDK's own source, deterministically, for every project with an older SDK in its venv. The `venv/bin/python*` notices are the scan reading the interpreter through the link; whether the 7-byte run was in the original binary or appeared after corruption is **not established** (G4: unproven which bytes) — and is moot once the walk stops reading through links.
3. **The damage write is `_enforce_lf`, not the marker report.** After `run_update`, `upgrade_project` calls `_enforce_lf(project)` (`scaffold_update.py:238` → `scaffold.py:144-159`). That helper walks `root.rglob("*")`, and its `entry.is_file()` **follows symlinks**: `venv/bin/python` → the real interpreter, `is_file()` True. It reads the binary, and a multi-MB Mach-O contains `\r\n` byte adjacencies (deterministic for real interpreter binaries; the fixture below makes it deterministic by construction). `entry.write_bytes(content.replace(b"\r\n", b"\n"))` then **writes back through the symlink**, changing the byte length of a live interpreter → `Malformed Mach-o file`. This is the only write in our tree that can reach outside the project root on this path: the restore loop (:240-245) writes only skip-pattern-matched paths, and the shipped patterns (`copier.yml: _skip_if_exists: [pyproject.toml, README.md, CLAUDE.md, tests/**, src/**]`) cannot match a `venv/...` relative path.

A third defect of the same family sits latent in (3): `_enforce_lf(project)` rewrites CRLF in **any** file under the project — including *tracked author files the update never touched*. A committed CRLF fixture or binary asset would be rewritten by a routine upgrade. Today it only surfaced through venv because tracked content is text and LF by convention; the mechanism permits it. The same fix cures it.

The skip-protected restore and the conflict report — the two protections the issue's reporter saw fire — are both built on the broken walk, which is why they produced noise instead of signal: the report listed venv files as "conflicted" while the actual corruption had already happened a few lines earlier.

## 1. The load-bearing insight: the clean-tree gate already defines "project content"

`upgrade_project` refuses a dirty tree before anything runs (`upgrade_dirty_tree:`, `scaffold_update.py:208-212`). So at walk time the tree is clean: tracked files match HEAD, and no untracked non-ignored file exists (porcelain would have shown it). Therefore:

- **Pre-update, "project content" is exactly `git ls-files`.** No parsing of `.gitignore` at all — no nested files, no negations, no `**` semantics, no global excludes file, none of the tar pit. Git's own view is the boundary.
- **Post-update, "files this run wrote" is exactly `git status --porcelain`** — every difference from HEAD was made by the update (the tree was clean when it started).

This answers the brief's Q1 by dissolving it: we do not determine "directories git ignores"; we determine "files git knows about", which is the set the update's own merge operates on and the set the author will commit. The edge cases land on existing behavior:

| Case | What happens |
|---|---|
| Project is not a git repo | Unreachable — `upgrade_requires_git:` refuses at :192-197 before any walk |
| `.gitignore` missing | Irrelevant — the mechanism never reads it |
| `git` binary absent | Already fatal earlier — the `status` pre-check fails and `upgrade_requires_git:` refuses at :203-207 |
| Ignored file the update writes into | Disclosed residual (§7 D2): porcelain hides ignored paths, so such a file gets no LF pass and no conflict notice. Today it *is* walked; the narrowing trades that for never touching venv. Reopen trigger D2. |
| The other `_enforce_lf` caller (`scaffold.py:377`, staging) | Not a git repo and never a project: it is a fresh materialized render containing only regular files (`_materialize_template` writes `write_bytes` members, no links possible). Keeps the rglob mode; the symlink gate applies vacuously. |

Weighing the alternatives for completeness: `git check-ignore` (per-path or batched via `--stdin`) reproduces git's ignore semantics but still needs the untracked-non-ignored case handled separately and adds a subprocess dance to no benefit over ls-files; in-process parsing (`pathspec`-style) re-implements git semantics the project never needs to agree with and adds a dependency posture question. Both lose to "ask git what it tracks". The design uses `git ls-files -z` and `git status --porcelain -z` (NUL-separated: no quoting, no `core.quotePath` escapes; rename/copy records carry the pre-image as a following field — the parser takes the first path of each record pair and consumes the second for `R`/`C`).

## 2. The symlink rule (brief Q2)

**The upgrade walk treats any final-component symlink — or Windows junction — as not project content: excluded from every read and write set, collected into a `skipped` list, surfaced as one CLI notice.** Writes through symlinks are refused categorically, including symlinks that resolve *inside* the root. This is deliberately stricter than the issue's minimum ask (outside-root only), and the strictness costs nothing:

- An inside-root target is reached by its own real path when it is inside the walked set, so permitting through-writes would only double-process content — never add reach.
- A categorical rule has no containment comparison to get wrong (no `resolve()` chains, no dangling-link edge in the guard), and it matches the repo's own walk precedents: `packaging.inventory` refuses any symlink (`packaging.py:36`), `standards_sync._sweep_vendored_tree` refuses symlink-or-junction with the note that `rglob` never descends linked directories (`standards_sync.py:448-455`) — which is why the exposure here is final-component file links exactly like `venv/bin/python`.

Mechanism, named: **lstat-based gate then write** — `entry.is_symlink() or entry.is_junction()` at walk time (both precedented in-tree; `Path.is_junction` is fine on this repo's `requires-python >= 3.13`), and the write helper re-checks the same gate immediately before `write_bytes`. This is gate-then-write, not an atomic `O_NOFOLLOW` open: a racing local adversary could swap the path between gate and write, and the design does not claim otherwise (G4: the guard's stated scope is accidental traversal — the reported defect class — not a concurrent-attacker model; a local CLI operating on a tree the operator was just told to keep clean has no such adversary). The atomic `O_NOFOLLOW` write helper is deferred with a trigger (§7 D3). The existing symlink-refusing `read_file` (`presentation.py:136-161`) is a *read*-side dirfd walk with a Windows fallback — reused by L6, not needed here because the walk excludes links before any read happens.

## 3. What the operator sees (brief Q3)

- **Ignored and untracked trees produce no output.** `venv/` is not project content; the 4,000-line skip dump some naive fix would print is the same noise as the bug, inverted. The silence is a documented contract (module docstring + user guide): the upgrade reads and writes the git-tracked set plus what the update itself changed — nothing else.
- **A tracked symlink produces one yellow line**: `skipped {path}: a symlink is not upgraded through — the upgrade never reads or writes through a link` (tracked links are rare, so this is one line, not a flood; the list is bounded by what git tracks).
- **The false-notice class disappears**: the installed-SDK-in-venv `<<<<<<<` literal can no longer be reported because venv is never read.
- `upgrade_project` returns a **3-tuple** `(conflicted, restored, skipped)`; the CLI prints restored lines, conflict lines, then skipped lines, then the L6 staleness notice. L6's record pinned the 2-tuple *for L6's slice* ("its 2-tuple contract and its test suite stay pinned" — `2026-10-17-issue460…design.md` §4); L7 owns this file and supersedes that pin deliberately. Callers: `cli.py:upgrade_command` (one unpack) and the existing test lane — a mechanical update, no second consumer exists to justify a result object over the grown tuple.

## 4. Same-hazard audit of the whole path (brief Q4)

| Surface | Verdict | Evidence |
|---|---|---|
| `_project_files` → `_protected_snapshot` (pre-update read) | **Fixed** — walks `git ls-files` paths, gate skips links | `scaffold_update.py:45-50, 73-90` |
| `_project_files` → conflict scan (post-update read) | **Fixed** — walks tracked ∪ porcelain paths, gate skips links | `scaffold_update.py:246-250` |
| `_enforce_lf(project)` — the damage write and the tracked-author-CRLF latent defect | **Fixed** — narrows to the update's write-set (porcelain paths), gate skips links, writes through the guarded helper | `scaffold.py:144-159`, call at `scaffold_update.py:238` |
| Restore write loop | **Fixed by construction + guarded** — keys come from the fixed snapshot walk; the write goes through the same gate-then-write helper (a path that became a link mid-update is refused, not followed) | `scaffold_update.py:240-245` |
| `_enforce_lf(staging)` (the `new` lane) | **Safe by construction** — materialized members only, no links possible; gate applies vacuously in rglob mode | `scaffold.py:117-141, 377` |
| L6 surfaces (`migrate_ui`, the staleness notice) | **Safe by construction** — envelope-driven, no tree walk, reads through symlink-refusing `read_file` | L6 record §3; `cli.py:_ui_staleness_notice` |
| `adopt_project` answers write | Safe — refuses a symlinked answers name explicitly (dangling-link precedent) | `scaffold_update.py:318-325` |
| `packaging`, `standards_sync` walks | Already guarded — the precedents this design extends | `packaging.py:23-75`, `standards_sync.py:440-460` |
| copier's `run_update` internals | **Out of our tree; disclosed boundary.** The venv damage is fully ours (`_enforce_lf`), but a *tracked* symlink sitting on a template-managed path (an author commits a link where the template renders a file) could still be written through by copier's own merge. Our guard covers our reads and writes, not copier's. Residual; §7 D5. | — |

## 5. Mechanism spec (for the build pass — no code written here)

1. **`scaffold_update.py`** gains two private helpers:
   - `_git_project_paths(project) -> tuple[list[str], list[str]]`: `(tracked, changed)` from one `git ls-files -z` call and one `git status --porcelain -z` call (subprocess shape identical to the existing `status` pre-check — `# noqa: S603, S607` precedent). The `-z` parser: split on NUL, drop the empty tail; for each record strip the two-letter XY; when `X` or `Y` is `R`/`C` the following record is the pre-image — consume it, keep the first path. Missing-on-disk paths (deletions) are dropped by the walk, not the parser.
   - `_walk_content(project, relatives) -> tuple[list[Path], list[str]]`: for each relative path, `entry = project / relative`; skip silently when the path no longer exists; when `entry.is_symlink() or entry.is_junction()` append to `skipped` and continue; when `entry.is_file()` append to files. (No `rglob` anywhere in project mode; the `.git`-parts filter is vestigial there and stays only in the staging mode below.)
2. **`_enforce_lf`** (`scaffold.py:144`) grows `*, paths: list[str] | None = None`. `None` keeps today's rglob behavior (the staging caller, `scaffold.py:377`, unchanged call site). With `paths`, it walks exactly those relatives through the same gate (skipped links: skipped — CRLF normalization of a link target is out of scope by §2), and its write goes through the guarded write helper. The docstring's "every template member is text" framing is corrected to the two modes: staging = rendered members; project = the update's write-set.
3. **The guarded write helper** (module-local, `scaffold_update.py`): `path.is_symlink() or path.is_junction()` → raise `ValueError` (internal invariant breach — a gated path reaching the writer is a bug, not an operator condition; no STD-4 prefix needed for an unreachable arm, but the message names the path for the traceback); else `write_bytes`. Used by the restore loop and (via `_enforce_lf`'s project mode) the LF pass.
4. **`upgrade_project`**:
   - `_protected_snapshot` builds from `tracked` (pre-update: tracked == all non-ignored content, §1).
   - after `run_update` and before the LF pass, compute `changed = porcelain paths`; `_enforce_lf(project, paths=sorted(set(changed) | {"…"})` — exactly the update's write-set (this is what cures the tracked-author-CRLF defect: author files outside the delta are never rewritten).
   - conflict scan walks `tracked ∪ changed` through `_walk_content`.
   - returns `(conflicted, restored, skipped)`.
5. **`cli.py:upgrade_command`**: unpacks three; prints the skipped lines after the restore lines (`yellow`), before the L6 staleness notice. No new refusal prefixes (STD-4 surface unchanged: the same four `upgrade_*:` refusals; skipping is not refusal).
6. **Docs**: module docstring and `upgrade_project` docstring carry the walk contract ("the upgrade reads and writes the git-tracked set plus what the update itself changed; it never parses ignore rules and never traverses a symlink"); `user_guide/plugin-sdk.qmd`'s upgrade section gains one paragraph in the same register (document-writer dispatch per the CLAUDE.md documentation register rule). No template/ or SRF-1 surface changes.

## 6. Minimal first slice

In scope: everything in §5, the fixture and controls in §8, the two docstring/user-guide touches, the caller/test-lane 3-tuple updates.

Not in scope by construction: any change to `copier`'s own behavior (upstream), any shared walk-safety module extraction (L6 explicitly left that question to this record — answer: **not this slice**; one consumer does not justify a module, §7 D1), any scaffold-template change (SRF-1 untouched), any standards/vendored bytes (STD-1/STD-5 untouched).

## 7. Deferrals (id / deferred / home / reopen trigger)

| id | deferred | home | reopen trigger |
|----|----------|------|----------------|
| D1 | shared "never walk ignored trees / never traverse links" helper module unifying `read_file`, the packaging gates, and this walk | follow-on issue on the gateway tracker | a second consumer asks for the shared shape (the L6-named maintainer preference counts as the first ask; until then the duplication is three small gates, not a module) |
| D2 | visibility when the update writes into an author-ignored path (porcelain hides it: no LF pass, no conflict notice) | follow-on issue | a tracker report of conflict markers or CRLF left in a file the author's own `.gitignore` ignores after an upgrade |
| D3 | atomic `O_NOFOLLOW`/dirfd write helper (racing-adversary grade) | follow-on issue | a threat model that includes a local concurrent adversary for `upgrade` (none exists today; gate-then-write is disclosed as such) |
| D4 | a Windows junction fixture arm in CI (the `is_junction` gate is code-covered cross-platform; a real junction needs `mklink /J`, no privilege, but the arm is CI plumbing) | follow-on issue or the next Windows-lane slice | a Windows CI flake or tracker report implicating a junction on the upgrade path |
| D5 | copier writing through a *tracked* symlink on a template-managed path (§4 last row) | upstream copier issue, linked from a gateway note | a tracker report of an upgrade damaging a link target on a template-managed path |

## 8. Proof — pre-committed acceptance rule (written before any build)

**Fixture** (offline, on the existing `tests/test_scaffold_update.py` lane — `_build_tagged_template_repo` :159-176, `target_ref` pointing at the throwaway tag; the lane already runs on ubuntu/macOS/Windows per `docs/internal/drift-and-obligations.md` row `sdk`):

- A project with `.gitignore` containing `venv/` (the template ships none — the repro's ignore was the author's own).
- `outside/interpreter` — a file **outside the project root** whose bytes contain both `\r\n` pairs and a `<<<<<<<` run (deterministic stand-in for the interpreter: it reproduces both the corruption trigger and the false-notice trigger; a real Mach-O cannot ship in a fixture).
- `venv/bin/python`, `venv/bin/python3`, `venv/bin/python3.13` → symlinks to `outside/interpreter` (symlink creation is skipped where the platform/privilege refuses — the same held-lane pattern the file already uses for missing git; Windows junction coverage is D4).
- `venv/lib/python3.13/site-packages/benchweave_sdk/scaffold_update.py` containing the `_CONFLICT_MARKER = b"<<<<<<<"` literal — the reported false-positive class.
- A tracked author file matching a skip pattern (`tests/crlf-fixture.md`) with deliberate CRLF bytes, **not** in the update's delta.
- A target-template member rendered with CRLF bytes (the throwaway target repo can carry them) — the PR #93 positive control.

**Acceptance rule — PASS requires every clause, machine-checked in the test:**

- **AR-1 (the issue's core demand)**: `sha256(outside/interpreter)` computed before `upgrade_project(...)` equals the hash computed after. Byte equality, not mtime, not absence-of-exception.
- **AR-2**: no returned path in `conflicted`, `restored`, or `skipped` starts with `venv/` — the venv is invisible to the report in all three channels.
- **AR-3**: the tracked author CRLF file is byte-identical after the upgrade (the update did not touch it; the upgrade must not either).
- **AR-4**: the update-written CRLF member ends LF-only (the narrowing did not over-narrow — PR #93's lane still holds).
- **AR-5**: a tracked symlink in the project appears in `skipped` exactly once, and the CLI renders one line for it.
- **RED control (the falsifier, run before GREEN is claimed)**: with the fix reverted (the parent commit checked out, or the guard neutralized in-place), the same test **must fail** on AR-1 with a hash mismatch — and, on the unpatched walk, AR-2 fails with the `venv/lib/.../scaffold_update.py` notice. A test that cannot be made to fail this way has not reproduced the defect: the fixture is void and the builder returns to re-fixture rather than shipping a green-but-empty proof. This clause is the difference between "asserts the fix" and "proves the bug existed".

**Don't-build check**: the evidence does not point anywhere near DON'T-BUILD — this is a reproduced data-loss defect with a mechanism fully located in our tree (§0), a fix that rides an invariant the command already enforces (§1), and precedents for every guard it introduces (§2, §4).

## 9. Invariant and cross-surface impacts

- **STD-4**: no new refusal prefixes; the existing four `upgrade_*:` refusals keep their arities. The write helper's internal `ValueError` is an unreachable-invariant arm, not an operator refusal.
- **SRF-1**: untouched — no template, no scaffold-output change.
- **CLI-visible behavior** (drift-and-obligations row 1, 🪝): the `upgrade` output gains the skipped-lines channel — this record is the drift note; the user-guide paragraph rides the slice.
- **Test lane**: `tests/test_scaffold_update.py` is the only suite whose contract changes (2-tuple → 3-tuple unpacks); `sdk` CI row already runs this file on all three OSes with the scaffold extra and full checkout history.
- **L6 adjacency**: L6's §4 staleness notice and `migrate-ui` are untouched; their "no tree walk" posture becomes the shared rule this slice enforces on the remaining walker.

## 10. Review tier

Tier 2 (#254): no `standards/` bytes, no control-path/admission/digest surface; a CLI-visible behavior change with a data-loss fix behind it. The increment loop's refute pass runs (damage-class fix); the code-reviewer agent gates the PR per its routing (CLI/docs surface).
