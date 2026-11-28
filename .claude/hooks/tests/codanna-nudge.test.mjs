// codanna-nudge.test.mjs — the PostToolUse nudge (.claude/hooks/codanna-nudge.ts).
//
// The hook gives one advisory per session: the first time a session reaches for a search
// before it has used Codanna. Any Codanna call, on the MCP surface or on the CLI, disarms
// it for the rest of the session. The CLI half matters most: a subagent in a worktree
// cannot call mcp__codanna__* at all, so the CLI is its only route.
//
// The suite runs the real hook. Under node, and under bun when bun is on PATH: bun is the
// interpreter .claude/settings.json uses. No CI lane in this repository runs this suite.
//
// What this suite does NOT catch:
// - A live harness. Every event is fed to the hook over stdin. That Claude Code delivers
//   this shape at PostToolUse is not proved here.
// - A search that is not the first word of a Bash command (`cd sub && rg x`). The hook
//   does not nudge for it, and no test says whether it should.
// author: Stephen Eaton

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const HOOK = join(HERE, "..", "codanna-nudge.ts");
const MARKER_DIR = "claude-codanna-nudge";

const NODE = { label: "node", command: [process.execPath, "--no-warnings"] };
const BUN = { label: "bun", command: ["bun"] };
const HAS_BUN = spawnSync("bun", ["--version"]).status === 0;
const WIN32 = process.platform === "win32" ? "os.tmpdir() ignores TMPDIR on Windows" : false;

const scratch = [];
test.after(() => {
  for (const dir of scratch) rmSync(dir, { recursive: true, force: true });
});

// A private world: its own TMPDIR, so the session markers never meet another run's, and
// its own checkout with a Codanna config (or none).
function world({ indexed = true } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "codanna-nudge-"));
  scratch.push(dir);
  const markers = join(dir, "markers");
  mkdirSync(markers);
  const checkout = join(dir, "checkout");
  mkdirSync(join(checkout, ".codanna"), { recursive: true });
  if (indexed) writeFileSync(join(checkout, ".codanna", "settings.toml"), 'workspace_root = "."\n');
  return { markers, checkout };
}

// One event over stdin. CLAUDE_PROJECT_DIR is dropped from the child's environment: the
// hook falls back to it when an event carries no cwd, and this process has one.
function fire(w, runtime, event, env = {}) {
  const { CLAUDE_PROJECT_DIR: _omitted, ...inherited } = process.env;
  const run = spawnSync(runtime.command[0], [...runtime.command.slice(1), HOOK], {
    input: event.raw ?? JSON.stringify({ cwd: w.checkout, ...event.e }),
    encoding: "utf8",
    env: { ...inherited, TMPDIR: w.markers, ...env },
  });
  const sessionId = event.e?.session_id ?? "unknown";
  const markerPath = join(w.markers, MARKER_DIR, `${sessionId}.json`);
  return {
    status: run.status,
    stdout: run.stdout,
    stderr: run.stderr,
    marker: (() => {
      try {
        return JSON.parse(readFileSync(markerPath, "utf8"));
      } catch {
        return null;
      }
    })(),
  };
}

function assertSilent(r) {
  assert.equal(r.status, 0, `the hook must exit 0\n${r.stderr}`);
  assert.equal(r.stderr, "", "a silent run writes nothing to stderr");
  assert.equal(r.stdout, "", "a silent run writes nothing to stdout");
}

function assertNudged(r) {
  assert.equal(r.status, 2, `a nudge is exit 2\nstderr: ${r.stderr}`);
  assert.equal(r.stdout, "", "the advisory goes to stderr, never to stdout");
  assert.match(r.stderr, /Codanna nudge/);
  assert.match(r.stderr, /mcp__codanna__semantic_search_with_context/, "the MCP route is named");
  assert.match(r.stderr, /codanna mcp semantic_search_with_context/, "the CLI route is named");
}

const CLI_CALL = { tool_name: "Bash", tool_input: { command: "codanna mcp find_symbol x --json" } };
const MCP_CALL = { tool_name: "mcp__codanna__find_symbol" };
const GREP = { tool_name: "Grep" };
const withSession = (id) => ({ session_id: id });

describe("under node", { skip: WIN32 }, () => {
  test("node runs the hook file", () => {
    // The hook is TypeScript and node strips the types itself. A node that cannot do
    // that would leave every arm below failing for the wrong reason.
    assertSilent(fire(world(), NODE, { e: { ...withSession("canary"), tool_name: "Read" } }));
  });

  test("the first search of a session nudges", () => {
    const w = world();
    assertNudged(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
  });

  test("the second search of the same session is silent", () => {
    const w = world();
    fire(w, NODE, { e: { ...withSession("one"), ...GREP } });
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
  });

  test("a nudge records itself in the session marker", () => {
    const w = world();
    const r = fire(w, NODE, { e: { ...withSession("one"), ...GREP } });
    assert.equal(r.status, 2);
    assert.deepEqual(r.marker, { codanna: false, nudged: true });
  });

  for (const [label, command] of [
    ["rg", "rg -n target src"],
    ["grep", "grep -n target file"],
    ["an indented grep", "  grep -n target file"],
  ]) {
    test(`a Bash search with ${label} nudges`, () => {
      const w = world();
      assertNudged(fire(w, NODE, { e: { ...withSession("one"), tool_name: "Bash", tool_input: { command } } }));
    });
  }

  for (const tool of ["Read", "Write", "Edit"]) {
    test(`${tool} is not a search: no nudge, no marker`, () => {
      const w = world();
      const r = fire(w, NODE, { e: { ...withSession("one"), tool_name: tool } });
      assertSilent(r);
      assert.equal(r.marker, null, "a tool that is not a search must not write a marker");
    });
  }

  test("a Bash command that is not a search does not nudge", () => {
    const w = world();
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), tool_name: "Bash", tool_input: { command: "git status --short" } } }));
  });

  test("a binary whose name only starts with rg is not a search", () => {
    const w = world();
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), tool_name: "Bash", tool_input: { command: "rgx target" } } }));
  });

  test("a tool that is not a search leaves the first search a first search", () => {
    const w = world();
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), tool_name: "Read" } }));
    assertNudged(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
  });

  test("a Codanna MCP call disarms the session", () => {
    const w = world();
    const r = fire(w, NODE, { e: { ...withSession("one"), ...MCP_CALL } });
    assertSilent(r);
    assert.deepEqual(r.marker, { codanna: true, nudged: false });
  });

  test("a search after a Codanna MCP call is silent", () => {
    const w = world();
    fire(w, NODE, { e: { ...withSession("one"), ...MCP_CALL } });
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
  });

  test("a Codanna CLI call disarms the session", () => {
    const w = world();
    const r = fire(w, NODE, { e: { ...withSession("one"), ...CLI_CALL } });
    assertSilent(r);
    assert.deepEqual(r.marker, { codanna: true, nudged: false });
  });

  test("a search after a Codanna CLI call is silent", () => {
    const w = world();
    fire(w, NODE, { e: { ...withSession("one"), ...CLI_CALL } });
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
  });

  test("a Codanna CLI call after a nudge is still recorded as a Codanna call", () => {
    const w = world();
    fire(w, NODE, { e: { ...withSession("one"), tool_name: "Bash", tool_input: { command: "rg target" } } });
    const r = fire(w, NODE, { e: { ...withSession("one"), ...CLI_CALL } });
    assertSilent(r);
    assert.deepEqual(r.marker, { codanna: true, nudged: true });
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
  });

  // The CLI call is recognised by its position in the command, not by its tool name: the
  // tool name for a CLI call is only "Bash".
  for (const [label, command] of [
    ["after &&", "cd sub && codanna retrieve calls alpha"],
    ["after ;", "true; codanna index"],
    ["after ||", "false || codanna dump"],
  ]) {
    test(`a Codanna CLI call ${label} disarms the session`, () => {
      const w = world();
      const r = fire(w, NODE, { e: { ...withSession("one"), tool_name: "Bash", tool_input: { command } } });
      assertSilent(r);
      assert.deepEqual(r.marker, { codanna: true, nudged: false });
    });
  }

  test("a Bash command that only mentions codanna does not disarm the session", () => {
    const w = world();
    const r = fire(w, NODE, { e: { ...withSession("one"), tool_name: "Bash", tool_input: { command: "echo codanna" } } });
    assertSilent(r);
    assert.equal(r.marker, null, "a mention is not a Codanna call");
    assertNudged(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
  });

  test("a disarmed session stays disarmed after a search", () => {
    const w = world();
    fire(w, NODE, { e: { ...withSession("one"), ...CLI_CALL } });
    fire(w, NODE, { e: { ...withSession("one"), ...GREP } });
    assert.deepEqual(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }).marker, { codanna: true, nudged: false });
  });

  test("a checkout with no Codanna config is never nudged and writes no marker", () => {
    const w = world({ indexed: false });
    const r = fire(w, NODE, { e: { ...withSession("one"), ...GREP } });
    assertSilent(r);
    assert.equal(r.marker, null);
  });

  test("two sessions are independent: each gets its one nudge", () => {
    const w = world();
    assertNudged(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
    assertSilent(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }));
    assertNudged(fire(w, NODE, { e: { ...withSession("two"), ...GREP } }));
  });

  test("events with no session id share one marker: nudged once", () => {
    const w = world();
    assertNudged(fire(w, NODE, { e: { ...GREP } }));
    assertSilent(fire(w, NODE, { e: { ...GREP } }));
  });

  test("malformed stdin: exit 0 and silent", () => {
    assertSilent(fire(world(), NODE, { raw: "{not json" }));
  });

  test("empty stdin: exit 0 and silent", () => {
    assertSilent(fire(world(), NODE, { raw: "" }));
  });

  test("an event with no tool name: exit 0 and silent", () => {
    assertSilent(fire(world(), NODE, { e: withSession("one") }));
  });

  test("an event with no cwd reads CLAUDE_PROJECT_DIR", () => {
    const w = world();
    const r = fire(w, NODE, { raw: JSON.stringify({ ...withSession("one"), ...GREP }) }, { CLAUDE_PROJECT_DIR: w.checkout });
    assertNudged(r);
  });

  test("a cwd that does not exist: exit 0 and silent", () => {
    const w = world();
    assertSilent(fire(w, NODE, { e: { cwd: join(w.checkout, "gone"), ...withSession("one"), ...GREP } }));
  });
});

describe("under bun", { skip: WIN32 || (HAS_BUN ? false : "bun is not on PATH: the interpreter settings.json uses is not exercised") }, () => {
  test("bun runs the hook file", () => {
    assertSilent(fire(world(), BUN, { e: { ...withSession("canary"), tool_name: "Read" } }));
  });

  test("the first search nudges, the second is silent, a CLI call disarms", () => {
    const w = world();
    assertNudged(fire(w, BUN, { e: { ...withSession("one"), ...GREP } }));
    assertSilent(fire(w, BUN, { e: { ...withSession("one"), ...GREP } }));
    assert.deepEqual(fire(w, BUN, { e: { ...withSession("two"), ...CLI_CALL } }).marker, { codanna: true, nudged: false });
    assertSilent(fire(w, BUN, { e: { ...withSession("two"), ...GREP } }));
  });

  test("node and bun leave the same marker for the same session", () => {
    const w = world();
    fire(w, NODE, { e: { ...withSession("one"), ...GREP } });
    fire(w, BUN, { e: { ...withSession("one"), ...CLI_CALL } });
    assert.deepEqual(fire(w, NODE, { e: { ...withSession("one"), ...GREP } }).marker, { codanna: true, nudged: true });
  });
});
