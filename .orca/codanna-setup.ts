#!/usr/bin/env bun
// codanna-setup.ts — Orca scripts.setup: build a worktree-local Codanna index so
// the project .mcp.json server (codanna serve --watch) and the CLI both answer
// from THIS worktree's files.
// Fail-soft: never blocks worktree creation; problems go to the log and stderr.
// author: Stephen Eaton
//
// Options (environment):
//   CODANNA_SEED_FROM_ROOT=1  copy the primary checkout's .codanna/index first, then
//                             re-index. Faster on big repos ONLY if the index stores
//                             relative paths (unverified). Test before enabling.
//   CODANNA_SETUP_THREADS=N   indexing threads (default: all cores)

import { appendFileSync, cpSync, existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";

const wt = process.env.ORCA_WORKTREE_PATH || process.cwd();
const root = process.env.ORCA_ROOT_PATH || "";
const name = process.env.ORCA_WORKSPACE_NAME || wt;

const codannaDir = join(wt, ".codanna");
const logFile = join(codannaDir, "setup.log");

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

  // 3. Build the index. No path argument: passing "." makes codanna rewrite the tracked
  //    settings.toml with an absolute workspace_root and an extra absolute root entry.
  const args = ["index", "--no-progress"];
  if (process.env.CODANNA_SETUP_THREADS) args.push("--threads", process.env.CODANNA_SETUP_THREADS);
  const start = performance.now();
  const code = codanna(args);
  const secs = Math.round((performance.now() - start) / 1000);
  if (code === 0) log(`index built in ${secs}s for ${name}`);
  else log(`codanna index failed (exit ${code}); agents will see exit code 7 and can re-run 'codanna index'`);

  // 4. Document collections (search_documents reads these, and the code index does not
  //    cover them). Indexing appends, so clear the store first or every run duplicates
  //    every chunk.
  const settingsText = existsSync(settings) ? readFileSync(settings, "utf8") : "";
  const collections = [...settingsText.matchAll(/^\[documents\.collections\.([^\]]+)\]/gm)].map((m) => m[1].trim());
  if (collections.length === 0) {
    log("no document collections configured; skipping document index");
    return;
  }
  rmSync(join(index, "documents"), { recursive: true, force: true });
  for (const c of collections) {
    const docCode = codanna(["documents", "index", "--collection", c, "--no-progress"]);
    log(docCode === 0 ? `documents indexed for collection ${c}` : `codanna documents index failed for ${c} (exit ${docCode})`);
  }
}

try { main(); } catch (err) { log(`setup error: ${(err as Error).message}`); }
process.exit(0);
