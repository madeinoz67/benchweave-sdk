#!/usr/bin/env bun
// codanna-reindex.ts — Claude Code PostToolUse hook (Edit|Write).
// Re-indexes the edited file, but only inside a Claude Code subagent worktree
// (.claude/worktrees/*). The main checkout and Orca worktrees run
// `codanna serve --watch`, so the hook does nothing there.
// Skips silently when the worktree has no Codanna config yet. Always exits 0.
//
// Runs under bun (its interpreter in .claude/settings.json) and under node (the hooks
// CI lane has no bun). Use node: modules only, never a Bun-only API.
// author: Stephen Eaton

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

type HookInput = { cwd?: string; tool_input?: { file_path?: string } };

async function main(): Promise<void> {
  let input: HookInput;
  try { input = JSON.parse(readFileSync(0, "utf8")) as HookInput; } catch { return; }

  const file = input.tool_input?.file_path;
  const cwd = input.cwd;
  if (!file || !cwd || !existsSync(cwd)) return;

  // git names the worktree root. When git is missing, or the cwd is not a checkout, the
  // status is not 0 and the hook stops here.
  const git = spawnSync("git", ["rev-parse", "--show-toplevel"], { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  if (git.status !== 0) return;
  const top = git.stdout.trim();

  // Only Claude Code subagent worktrees need this.
  if (!top.replaceAll("\\", "/").includes("/.claude/worktrees/")) return;
  if (!existsSync(join(top, ".codanna", "settings.toml"))) return;

  // Index just the changed file. Never use -f here: with a path, -f clears the whole index.
  // Errors (unsupported file type, index not built yet, codanna not installed) are ignored;
  // the agent re-indexes on exit code 7 if the index goes stale.
  spawnSync("codanna", ["index", file, "--no-progress"], { cwd: top, stdio: "ignore" });
}

try { await main(); } catch { /* never fail the tool call */ }
process.exit(0);
