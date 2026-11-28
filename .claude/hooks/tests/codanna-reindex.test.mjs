// codanna-reindex.test.mjs — the PostToolUse re-index (.claude/hooks/codanna-reindex.ts).
//
// The hook re-indexes the one file an edit touched, and only inside a Claude Code subagent
// worktree (a checkout whose root sits under .claude/worktrees/). Everywhere else it calls
// nothing.
//
// The argv is the subject. The hook hands the CLI an edited file's path, and a path is
// data that arrives where the CLI reads options. The call is `index --no-progress -- <path>`:
// the flags first, then `--`, then the path. After `--` the CLI reads every token as a path,
// so a file named like a flag is one path and not an option. Measured on codanna 0.18.0:
// without the separator, `codanna index -f` is the force flag, the index is rebuilt from its
// configured roots, and a file that was indexed on its own is gone from it.
//
// Every event is fed to the hook over stdin, and the `codanna` first on PATH is a stand-in
// that records its working directory and its argv. Those arms prove the argv the hook builds.
// One arm runs the real CLI, when it is on PATH, to prove what that argv does to an index.
//
// What this suite does NOT catch:
// - A live harness. That Claude Code delivers this shape at PostToolUse, with an absolute
//   `file_path`, is not proved here. An absolute path cannot begin with a hyphen, so the
//   flag-like shapes below are relative paths, which is the worst an event can carry.
// - That the real CLI indexed the file. The stand-in arms record the call and do nothing;
//   the real-CLI arm proves one file is left in the index, not that another was added.
// - What the CLI does with a path that contains a newline or a NUL. Neither is edited here.
// author: Stephen Eaton

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const HOOK = join(HERE, "..", "codanna-reindex.ts");

const NODE = { label: "node", command: [process.execPath, "--no-warnings"] };
const BUN = { label: "bun", command: ["bun"] };
const HAS_BUN = spawnSync("bun", ["--version"]).status === 0;
const HAS_CODANNA = spawnSync("codanna", ["--version"]).status === 0;
const WIN32 = process.platform === "win32" ? "the stand-in is a /bin/sh script" : false;

// One invocation is the working directory, then each argument, then an empty terminator,
// all NUL-separated. A NUL is the one byte a path cannot carry into a line-based log.
const STAND_IN = [
  "#!/bin/sh",
  `printf '%s\\0' "$(pwd)" "$@" >> "$REINDEX_STANDIN_LOG"`,
  `printf '\\0' >> "$REINDEX_STANDIN_LOG"`,
  'exit "${REINDEX_STANDIN_EXIT:-0}"',
  "",
].join("\n");

const scratch = [];
test.after(() => {
  for (const dir of scratch) rmSync(dir, { recursive: true, force: true });
});

// A private world: a checkout whose git root sits under .claude/worktrees/, a Codanna config
// in it or none, and a bin directory with the stand-in first on PATH.
function world({ inWorktree = true, indexed = true, sources = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "codanna-reindex-"));
  scratch.push(dir);
  const bin = join(dir, "bin");
  mkdirSync(bin);
  const log = join(dir, "argv.log");
  writeFileSync(join(bin, "codanna"), STAND_IN);
  chmodSync(join(bin, "codanna"), 0o755);

  const checkout = join(dir, "primary", ...(inWorktree ? [".claude", "worktrees", "lane-a"] : []));
  mkdirSync(checkout, { recursive: true });
  const init = spawnSync("git", ["init", "-q", checkout]);
  assert.equal(init.status, 0, `git init failed in the scratch checkout\n${init.stderr}`);
  if (indexed) {
    mkdirSync(join(checkout, ".codanna"));
    const roots = sources ? '\n[indexing]\nindexed_paths = ["src"]\nshow_progress = false\n' : "";
    writeFileSync(join(checkout, ".codanna", "settings.toml"), `workspace_root = "."\n${roots}`);
  }
  if (sources) {
    mkdirSync(join(checkout, "src"));
    mkdirSync(join(checkout, "other"));
    writeFileSync(join(checkout, "src", "probe.py"), "def alpha():\n    return 1\n");
    writeFileSync(join(checkout, "other", "extra.py"), "def extra_only():\n    return 7\n");
  }
  return { checkout, log, top: realpathSync(checkout), standInPath: `${bin}${delimiter}${process.env.PATH}` };
}

// One event over stdin. `path` picks the codanna the hook will find.
function fire(w, runtime, event, path = w.standInPath) {
  const run = spawnSync(runtime.command[0], [...runtime.command.slice(1), HOOK], {
    input: event.raw ?? JSON.stringify({ cwd: w.checkout, ...event.e }),
    encoding: "utf8",
    env: { ...process.env, PATH: path, REINDEX_STANDIN_LOG: w.log, ...event.env },
  });
  return { status: run.status, stdout: run.stdout, stderr: run.stderr };
}

// Every call the stand-in saw: [working directory, ...arguments].
function calls(w) {
  let raw;
  try {
    raw = readFileSync(w.log, "utf8");
  } catch {
    return [];
  }
  return raw.split("\0\0").filter(Boolean).map((call) => call.split("\0"));
}

function assertSilent(r) {
  assert.equal(r.status, 0, `the hook must exit 0\n${r.stderr}`);
  assert.equal(r.stderr, "", "a silent run writes nothing to stderr");
  assert.equal(r.stdout, "", "a silent run writes nothing to stdout");
}

const edit = (file_path) => ({ tool_input: { file_path } });

// The argv the fix is about: the flags, the separator, then the path as it was given.
function assertReindexed(w, file) {
  assert.deepEqual(calls(w), [[w.top, "index", "--no-progress", "--", file]]);
}

describe("under node, with the stand-in", { skip: WIN32 }, () => {
  test("node runs the hook file: the edited file is one path after the separator", () => {
    // If node could not run the hook file, the arms below would fail for the wrong reason.
    const w = world();
    const file = join(w.top, "src", "probe.py");
    assertSilent(fire(w, NODE, { e: edit(file) }));
    assertReindexed(w, file);
  });

  for (const name of ["-f", "--force", "-c", "--no-progress"]) {
    test(`a file named like a flag (${name}) is one path after the separator`, () => {
      const w = world();
      assertSilent(fire(w, NODE, { e: edit(name) }));
      const [argv] = calls(w);
      assert.ok(argv, "the hook made no index call");
      const separator = argv.indexOf("--");
      assert.ok(separator !== -1, `no separator in the argv: ${argv.join(" ")}`);
      // argv is [working directory, "index", ...flags, "--", ...paths].
      assert.deepEqual(argv.slice(2, separator), ["--no-progress"], "only the flags come before --");
      assert.deepEqual(argv.slice(separator + 1), [name], "the flag-like name comes after --");
      assert.equal(w.top, argv[0], "the CLI runs in the worktree root");
    });
  }

  test("a path with a space stays one argument", () => {
    const w = world();
    const file = join(w.top, "a b", "probe file.py");
    assertSilent(fire(w, NODE, { e: edit(file) }));
    assertReindexed(w, file);
  });

  test("a relative path is passed as it was given", () => {
    const w = world();
    assertSilent(fire(w, NODE, { e: edit("src/probe.py") }));
    assertReindexed(w, "src/probe.py");
  });

  test("outside a subagent worktree the hook calls nothing", () => {
    // A main checkout has a Codanna config too; what withholds the hook is where its root sits.
    const w = world({ inWorktree: false });
    assertSilent(fire(w, NODE, { e: edit(join(w.top, "src", "probe.py")) }));
    assert.deepEqual(calls(w), []);
  });

  test("a worktree with no Codanna config: no call", () => {
    const w = world({ indexed: false });
    assertSilent(fire(w, NODE, { e: edit(join(w.top, "src", "probe.py")) }));
    assert.deepEqual(calls(w), []);
  });

  test("an event with no file path: exit 0 and no call", () => {
    const w = world();
    assertSilent(fire(w, NODE, { e: { tool_input: {} } }));
    assertSilent(fire(w, NODE, { e: { tool_name: "Edit" } }));
    assert.deepEqual(calls(w), []);
  });

  test("malformed stdin: exit 0 and no call", () => {
    const w = world();
    assertSilent(fire(w, NODE, { raw: "{not json" }));
    assert.deepEqual(calls(w), []);
  });

  test("empty stdin: exit 0 and no call", () => {
    const w = world();
    assertSilent(fire(w, NODE, { raw: "" }));
    assert.deepEqual(calls(w), []);
  });

  test("a cwd that does not exist: exit 0 and no call", () => {
    const w = world();
    assertSilent(fire(w, NODE, { e: { cwd: join(w.top, "gone"), ...edit("-f") } }));
    assert.deepEqual(calls(w), []);
  });

  test("a CLI that fails never fails the tool call", () => {
    // An unsupported file type and an index not built yet are two ordinary failures here.
    const w = world();
    assertSilent(fire(w, NODE, { e: edit("notes.txt"), env: { REINDEX_STANDIN_EXIT: "1" } }));
    assert.equal(calls(w).length, 1, "the call is made once and not retried");
  });
});

describe("the real CLI", { skip: WIN32 || (HAS_CODANNA ? false : "codanna is not on PATH: the arm that proves what the argv does to an index does not run") }, () => {
  function cli(w, ...args) {
    return spawnSync("codanna", args, { cwd: w.top, encoding: "utf8" });
  }

  // How many rows find_symbol returns for `name`. A lookup that finds nothing answers with
  // a not_found envelope and `data: null`, so the envelope is read and the status is not.
  function found(w, name) {
    const run = cli(w, "mcp", "find_symbol", name, "--json");
    const envelope = JSON.parse(run.stdout);
    if (envelope.data === null) {
      assert.equal(envelope.status, "not_found", `null data on a ${envelope.status} answer`);
      return 0;
    }
    assert.ok(Array.isArray(envelope.data), `no data rows in the answer\n${run.stdout}${run.stderr}`);
    return envelope.data.length;
  }

  test("a flag-like path leaves a file indexed on its own in the index; the same token before the separator removes it", () => {
    const w = world({ sources: true });
    // `other/` is not a configured root, so the file is indexed on its own and a rebuild
    // from the roots does not bring it back.
    assert.equal(cli(w, "index", "--no-progress", "--", "other/extra.py").status, 0);
    assert.equal(found(w, "extra_only"), 1, "the precondition: the file is in the index");

    // The guard, through the real hook and the real CLI.
    assertSilent(fire(w, NODE, { e: edit("-f") }, process.env.PATH));
    assert.equal(found(w, "extra_only"), 1, "the re-index of a flag-like path rebuilt the index");

    // The control: the argv the hook built before the separator, which made the token a flag.
    const control = cli(w, "index", "-f", "--no-progress");
    assert.equal(control.status, 0, control.stderr);
    assert.equal(found(w, "extra_only"), 0, "-f is no longer the force flag: measure the CLI again");
  });
});

describe("under bun", { skip: WIN32 || (HAS_BUN ? false : "bun is not on PATH: the interpreter settings.json uses is not exercised") }, () => {
  test("bun runs the hook file and builds the same argv as node", () => {
    const w = world();
    const file = join(w.top, "-f");
    assertSilent(fire(w, NODE, { e: edit(file) }));
    const underNode = calls(w);
    assertSilent(fire(w, BUN, { e: edit(file) }));
    assert.deepEqual(calls(w), [...underNode, ...underNode]);
  });
});
