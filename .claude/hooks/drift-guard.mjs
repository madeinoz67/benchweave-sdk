#!/usr/bin/env node
// drift-guard.mjs — mechanical enforcement for the cross-surface obligations in
// docs/internal/drift-and-obligations.md.
//
// That document lists the "if a PR touches X, it must also do Y" obligations and is
// honest that most of them have no automated check. This hook covers the ones that are
// purely path-shaped, so they stop depending on a reviewer remembering. The rest need
// judgment (or a build) and stay manual — see the doc.
//
// Every rule WARNS, never blocks. Each fires at most once per session, and stays silent if
// the session already touched the surface it would ask about (where a legitimate paired
// surface exists — rules whose remedy is NOT another file in this repo use the
// once-per-session fired marker instead, because no edit here can quiet them). Add a rule
// by appending to RULES — nothing else here is rule-specific.

import { appendFileSync, existsSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, relative, sep } from 'node:path'

const DOCS = (p) => p.startsWith('user_guide/') || p === 'README.md' || p.startsWith('docs/internal/')

const RULES = [
  {
    // Obligation 1 — CLI behavior vs the user guide and the README's five steps.
    id: 'cli-docs-drift',
    triggers: (p) => p === 'src/benchweave_sdk/cli.py',
    satisfies: DOCS,
    message: [
      '**[Drift 1] `src/benchweave_sdk/cli.py` was edited — do the docs still match?**',
      '',
      'A command, flag, or output shape that changed needs its entry in',
      '`user_guide/plugin-sdk.qmd` and the README\'s five-steps section. Absence of the',
      'update is the finding, even when the diff touches no docs.',
    ],
  },
  {
    // Obligation 2 — scaffold output is an interface; generated docs move with it.
    id: 'scaffold-docs-drift',
    triggers: (p) => p === 'src/benchweave_sdk/scaffold.py',
    satisfies: DOCS,
    message: [
      '**[Drift 2] `scaffold.py` was edited — generated projects just changed shape.**',
      '',
      'Scaffold output reproduces into every downstream plugin repository and downstream',
      'repos diff it, so a shape change is an interface change. If the generated project',
      'looks different: update the scaffold\'s generated docs including the AI-GUIDE.md',
      'text carried in `scaffold.py`, the user guide, and the README five steps.',
    ],
  },
  {
    // Obligation 4 — packaging vs wheel/sdist contents and the install steps.
    id: 'packaging-drift',
    triggers: (p) => p === 'pyproject.toml' || p === 'hatch_build.py',
    satisfies: DOCS,
    message: [
      '**[Drift 4] Packaging was edited — do wheel/sdist contents and install steps match?**',
      '',
      'The wheel packages `src/benchweave_sdk` only and the sdist include list is explicit:',
      '`.claude/`, `.mcp.json`, `AGENTS.md` and `CLAUDE.md` must never appear in either',
      'artifact. The SDK is not yet on an index — installs name the built wheel explicitly,',
      'so the README install steps move with any packaging change.',
    ],
  },
  {
    // Obligation 5 — vendored bytes never change here first. Deliberately NOT
    // satisfiable by another edit in this repo: recording a hand-edit in the lock would
    // be the exact wrong remedy, so no SDK-side file quiets this rule — the once-per-
    // session fired marker provides the quieting.
    id: 'vendored-tree-drift',
    triggers: (p) => p.startsWith('src/benchweave_sdk/standards/'),
    satisfies: () => false,
    message: [
      '**[Drift 5] The vendored standards tree was touched — hand-edits are wrong regardless of quality.**',
      '',
      'The stamps say *generated — do not edit*: the change belongs in the main repository\'s',
      'canonical corpus, re-exported and re-synced with a standards version increment.',
      'Content changes arrive here only as a re-sync; `sync-standards --check` and the',
      'packaging hook must both stay green on the result.',
    ],
  },
  {
    // Obligation 3 — lock format changes carry compatibility notes; not quietable by
    // another file here.
    id: 'lock-format-drift',
    triggers: (p) => p === 'standards-lock.json',
    satisfies: () => false,
    message: [
      '**[Drift 3] `standards-lock.json` was edited — format changes carry compatibility notes.**',
      '',
      'A lock/bundle format change updates the compatibility notes inside the lock and,',
      'when the export format itself moved, the main repository\'s corpus export docs.',
      'Normative content still never changes here first.',
    ],
  },
  {
    // Obligation 7 — the renderer pairs with a main-side rebuild.
    id: 'renderer-assets-drift',
    triggers: (p) => p.startsWith('src/benchweave_sdk/preview_assets/'),
    satisfies: () => false,
    message: [
      '**[Drift 7] Committed renderer assets were touched — is a fresh build byte-identical?**',
      '',
      'The main repo\'s CI rebuilds the preview renderer and fails on any diff here, so a',
      'renderer-affecting UI change lands as a rebuild in the same change — hand-edited',
      'assets drift from the build that produces them.',
    ],
  },
  {
    // Obligation 9-equivalent — a dependency change means the lock moves in the same commit.
    id: 'dependency-lock-drift',
    triggers: (p) => p === 'pyproject.toml',
    satisfies: (p) => p === 'uv.lock',
    message: [
      '**[Drift] `pyproject.toml` was edited — does `uv.lock` move in the same commit?**',
      '',
      'A dependency add/remove/re-pin travels with its lock. Purely local config (tool',
      'settings, paths) can ignore this.',
    ],
  },
]

// A broken guard must never break the session: everything below is best-effort and always
// exits 0.
try {
  const input = JSON.parse(await readStdin())
  const filePath = input?.tool_input?.file_path
  if (!filePath) process.exit(0)

  const root = process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd()
  const rel = relative(root, filePath).split(sep).join('/')
  // Edits outside the repo are not our business.
  if (!rel || rel.startsWith('..')) process.exit(0)

  const stateDir = join(tmpdir(), 'benchweave-sdk-drift-guard', String(input.session_id || 'nosession'))
  mkdirSync(stateDir, { recursive: true })

  const notes = []
  for (const rule of RULES) {
    const satisfied = join(stateDir, `${rule.id}.satisfied`)
    const fired = join(stateDir, `${rule.id}.fired`)

    // Record satisfaction first, so an edit that both satisfies and triggers in the same
    // session resolves in favor of staying quiet.
    if (rule.satisfies(rel)) {
      appendFileSync(satisfied, `${rel}\n`)
      continue
    }
    if (!rule.triggers(rel)) continue
    if (existsSync(satisfied) || existsSync(fired)) continue

    appendFileSync(fired, `${rel}\n`)
    notes.push(rule.message.join('\n'))
  }

  if (notes.length) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PostToolUse',
          additionalContext: notes.join('\n\n---\n\n'),
        },
      })
    )
  }
} catch {
  // Swallow. A guard that fails closed would be worse than one that misses a warning.
}
process.exit(0)

async function readStdin() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  return Buffer.concat(chunks).toString('utf-8') || '{}'
}
