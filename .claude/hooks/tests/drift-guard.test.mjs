// Tests for drift-guard.mjs — the path-shaped cross-surface warning hook.
// Runs the real script end-to-end with a private session-id state dir.

import { spawnSync } from 'node:child_process'
import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import assert from 'node:assert/strict'

const HOOK = join(import.meta.dirname, '..', 'drift-guard.mjs')
const STATE = join(tmpdir(), 'benchweave-sdk-drift-guard')

function runWith(session, relPath) {
  const res = spawnSync('node', [HOOK], {
    input: JSON.stringify({
      session_id: session,
      cwd: process.cwd(),
      tool_input: { file_path: join(process.cwd(), relPath) },
    }),
    encoding: 'utf-8',
  })
  assert.equal(res.status, 0, `hook must always exit 0 (stderr: ${res.stderr})`)
  if (!res.stdout.trim()) return null
  return JSON.parse(res.stdout).hookSpecificOutput?.additionalContext ?? null
}

test.after(() => {
  rmSync(STATE, { recursive: true, force: true })
})

test('a trigger path warns once, then stays quiet for the session', () => {
  const s = 'dg-test-once'
  const first = runWith(s, 'src/benchweave_sdk/cli.py')
  assert.ok(first?.includes('Drift 1'), `expected the CLI-docs warning, got: ${first}`)
  const second = runWith(s, 'src/benchweave_sdk/cli.py')
  assert.equal(second, null, 'the same rule must not fire twice in one session')
})

test('touching the corresponding surface first silences the rule', () => {
  const s = 'dg-test-satisfy'
  assert.equal(runWith(s, 'README.md'), null)
  const then = runWith(s, 'src/benchweave_sdk/cli.py')
  assert.equal(then, null, 'satisfaction recorded first must quiet the trigger')
})

test('the vendored tree rule cannot be quieted by another vendored edit — it fires once on evidence of the class', () => {
  const s = 'dg-test-vendored'
  const first = runWith(s, 'src/benchweave_sdk/standards/otdp/0.1.0/otdp-runtime.schema.json')
  assert.ok(first?.includes('Drift 5'), `expected the vendored-tree warning, got: ${first}`)
  const second = runWith(s, 'src/benchweave_sdk/standards/registry/0.1.0/package-lock.schema.json')
  assert.equal(second, null, 'once-per-session fired marker quiets the class')
})

test('a path outside the repo produces no warning', () => {
  assert.equal(runWith('dg-test-outside', '/tmp/somewhere-else/entirely.py'), null)
})
