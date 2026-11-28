#!/usr/bin/env bun
// codanna-setup.ts — Orca scripts.setup: build a worktree-local Codanna CODE index.
// author: Stephen Eaton
//
// Orca starts the Claude agent and this script at the same time, so the .mcp.json
// server (/.orca/codanna-mcp.sh) waits for `.codanna/index.ready`. This script
// announces itself with `.codanna/setup-in-progress`, builds the code index, and
// writes the ready marker as soon as that index exists.
//
// Document collections are NOT indexed here. On a large repo (BenchWeave: ~5 min
// for docs + design) the cost is paid per worktree, and every Orca worktree is a
// short-lived automation lane that rarely reads prose. Code navigation — the
// surface the nudge advertises — needs only the code index. The primary checkout
// keeps its document index; a worktree that really needs doc search can run
// `codanna documents index --collection <name> --no-progress` once.
//
// Fail-soft: never blocks worktree creation; problems go to the log and stderr.
//
// Options (environment):
//   CODANNA_SEED_FROM_ROOT=1  copy the primary checkout's .codanna/index first, then
//                             re-index. Faster on big repos ONLY if the index stores
//                             relative paths (unverified). Test before enabling.
//   CODANNA_SETUP_THREADS=N   indexing threads (default: all cores)

import { appendFileSync, cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const wt = process.env.ORCA_WORKTREE_PATH || process.cwd();
const root = process.env.ORCA_ROOT_PATH || "";
const name = process.env.ORCA_WORKSPACE_NAME || wt;

const codannaDir = join(wt, ".codanna");
const logFile = join(codannaDir, "setup.log");
const setupFlag = join(codannaDir, "setup-in-progress");
const indexReady = join(codannaDir, "index.ready");

const stamp = () => new Date().toLocaleString("sv-SE"); // local time, YYYY-MM-DD HH:MM:SS
function log(msg: string): void {
  const line = `${stamp()} ${msg}\n`;
  try { appendFileSync(logFile, line); } catch { /* log dir missing: stderr only */ }
  process.stderr.write(line);
}

function codanna(args: string[]): number {
  const p = Bun.spawnSync(["codanna", ...args], { cwd: wt, stdout: "pipe", stderr: "pipe" });
  try {
    appendFileSync(logFile, p.stdout);
    appendFileSync(logFile, p.stderr);
  } catch { /* ignore */ }
  return p.exitCode ?? 1;
}

function main(): void {
  if (!existsSync(wt)) {
    process.stderr.write(`codanna-setup: worktree path not found: ${wt}\n`);
    return;
  }
  mkdirSync(codannaDir, { recursive: true });

  // Announce before touching the index. The MCP gate watches this flag, then
  // the ready marker below; a stale marker from a previous run must not win.
  try {
    rmSync(indexReady, { force: true });
    writeFileSync(setupFlag, "");
  } catch { /* the gate also handles a missing flag */ }

  try {
    if (!Bun.which("codanna")) {
      log("codanna not on PATH: skipping index build (install: brew install codanna)");
      return;
    }

    // 1. Config: prefer the committed settings.toml; else copy from root; else init.
    const settings = join(codannaDir, "settings.toml");
    if (!existsSync(settings)) {
      const rootSettings = root ? join(root, ".codanna", "settings.toml") : "";
      if (rootSettings && existsSync(rootSettings)) {
        cpSync(rootSettings, settings);
        log("copied settings.toml from primary checkout");
      } else if (codanna(["init"]) === 0) {
        log("ran codanna init");
      } else {
        log("codanna init failed; continuing with defaults");
      }
    }

    // 2. Optional seed (opt-in, unverified; see header).
    const index = join(codannaDir, "index");
    const rootIndex = root ? join(root, ".codanna", "index") : "";
    if (process.env.CODANNA_SEED_FROM_ROOT === "1" && rootIndex && existsSync(rootIndex) && !existsSync(index)) {
      cpSync(rootIndex, index, { recursive: true });
      log("seeded index from primary checkout");
    }

    // 3. Build the code index. No path argument: passing "." makes codanna rewrite
    //    the tracked settings.toml with an absolute workspace_root and an extra
    //    absolute root entry. Document status reports read this index too.
    const args = ["index", "--no-progress"];
    if (process.env.CODANNA_SETUP_THREADS) args.push("--threads", process.env.CODANNA_SETUP_THREADS);
    const start = performance.now();
    const code = codanna(args);
    const secs = Math.round((performance.now() - start) / 1000);
    if (code === 0) {
      writeFileSync(indexReady, "");
      log(`code index built in ${secs}s for ${name}; marked ready`);
    } else {
      log(`codanna index failed (exit ${code}); MCP gate falls through and serve will retry the build`);
    }
  } finally {
    // Always clear the flag: a crashed setup must not hold the MCP gate.
    try { rmSync(setupFlag, { force: true }); } catch { /* already gone */ }
  }
}

try { main(); } catch (err) { log(`setup error: ${(err as Error).message}`); }
process.exit(0);
