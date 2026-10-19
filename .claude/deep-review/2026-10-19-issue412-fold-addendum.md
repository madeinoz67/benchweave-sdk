# Issue #412 — fold-wave addendum (2026-10-19)

The design record (`2026-10-19-issue412-version-literal-gate-design.md`) is
frozen; its bytes are not edited. This addendum records what the 2026-10-19
fold wave changed relative to that record, row by row. Reading order: the
record first, then this.

## Surface-set deltas (the record's §3 mechanism, amended)

**F1 — symlinks under scanned surfaces (adversary, MED).** The record's
"every file under `website/`" was false for symlinked subtrees:
`Path.rglob` never descends a directory symlink and the link entry fails
`is_file`, so a whole subtree escaped both the scan and the census
(reproduced exit 0 with a claim planted behind the link). The mechanism now
carries an explicit fail-closed symlink policy: any symlink under a scanned
surface — or any of the four surface roots themselves — refuses with
`version_literal_count_failed` naming the path. Not a scan of symlink
targets: a refusal, so a planted target can never ride the link.

**F2 — `user_guide/` is directory-gated (adversary, MED).** The record
enumerated `user_guide/**/*.qmd`; a page renamed to `notes.md` (or
`NOTES.QMD` — the extension gate was case-sensitive on POSIX) escaped with
one edit. The enumeration is now every file under `user_guide/`, any name.

**F3 — non-UTF-8 bytes (adversary, LOW).** The record's "a count that
cannot be computed is a refusal" held at the exit code (raw
`UnicodeDecodeError` still exits 1) but not at the reader: the documented
`version_literal_count_failed` shape was not what appeared. The catch list
in `main()` now includes `UnicodeDecodeError`.

**F4 — OS junk names (adversary, LOW).** `.DS_Store`/`Thumbs.db` reddened
the census with an unsanctioned file. They are excluded BY NAME ONLY
(`PROSE_JUNK_NAMES`) — deliberately not a general ignore mechanism: a file
is prose-scanned and census-counted unless it carries one of those two
names.

## Deferral F2a (new, per the deferral-row contract)

| id | deferred | home | reopen trigger |
|---|---|---|---|
| F2a | root-level `*.md` surfaces other than `README.md` | follow-on on issue #412 (this tracker) | a three-component version claim landing on a root-level `*.md` surface other than `README.md`/`CHANGELOG.md`, observed in a release-review walk or the version-surface census — or the tokenisation end-state (record deferral V2) absorbing generated history so `CHANGELOG.md`'s 128 measured literals can be counted without a blanket register |

The F2 fold instruction asked whether widening onto root `*.md` was free.
Measured 2026-10-19 at the fold tip: it is NOT — the SDK root carries
eight `*.md` files including `CHANGELOG.md` (the record's measured 128
generated literals) and the `AGENTS.md`/`CLAUDE.md` convention files, so
the widening would force exactly the blanket-absorbing register the record
rejected in §5. The boundary therefore stays `README.md`-only and is named
here rather than left silent. (The record's §2 census already excluded
`CHANGELOG.md` and `docs/**` by name; this row extends that discipline to
the remaining root-level `*.md`.)

## Records correction (governor, F5)

`docs/internal/release-review-matrix.md`'s v0.16.0 walk row 5 recorded a
badge walk "confirming" against the lock at a pin where four of seven
badges were stale, and said six where seven families exist since v0.13.0.
An append-only dated correction (`5-corr`) is inserted under the original
row, which is untouched. The governor's condition: this lands before the
next release cut re-uses the walk. The governor's NIT on the drift
obligation row 10's motion list folds into the gateway obligation-18
amendment when that lands (the record's R2 ordering).

## Numbers at the fold tip (for AR re-runs)

- Prose surface: 11 scanned files (census unchanged — `user_guide/` still
  carries exactly its five committed pages; junk names are excluded, not
  counted).
- Prose sites: 67 (the record's 68 was measured before the AR-4 wording
  amendments made `index.qmd` versionless; the badge/link edits are
  count-neutral).
- `TestProseScope` remains exactly the record's 7 arms; the fold arms live
  in `TestProseFoldHardening` (F1, F2 ×2, F3, F4 — F5 is a records row
  with no arm).
