#!/usr/bin/env bun
// codanna-reindex.ts — Claude Code PostToolUse hook (Edit|Write).
// Re-indexes the edited file, but only inside a Claude Code subagent worktree
// (.claude/worktrees/*). The main checkout and Orca worktrees run
// `codanna serve --watch`, so the hook does nothing there.
// Skips silently when the worktree has no Codanna config yet. Always exits 0.
// author: Stephen Eaton

import { existsSync } from "node:fs";
import { join } from "node:path";

type HookInput = { cwd?: string; tool_input?: { file_path?: string } };

async function main(): Promise<void> {
  let input: HookInput;
  try { input = (await Bun.stdin.json()) as HookInput; } catch { return; }

  const file = input.tool_input?.file_path;
  const cwd = input.cwd;
  if (!file || !cwd || !existsSync(cwd)) return;
  if (!Bun.which("codanna") || !Bun.which("git")) return;

  const git = Bun.spawnSync(["git", "rev-parse", "--show-toplevel"], { cwd, stdout: "pipe", stderr: "ignore" });
  if (git.exitCode !== 0) return;
  const top = git.stdout.toString().trim();

  // Only Claude Code subagent worktrees need this.
  if (!top.replaceAll("\\", "/").includes("/.claude/worktrees/")) return;
  if (!existsSync(join(top, ".codanna", "settings.toml"))) return;

  // Index just the changed file. Never use -f here: with a path, -f clears the whole index.
  // Errors (unsupported file type, index not built yet) are ignored; the agent
  // re-indexes on exit code 7 if the index goes stale.
  Bun.spawnSync(["codanna", "index", file, "--no-progress"], { cwd: top, stdout: "ignore", stderr: "ignore" });
}

try { await main(); } catch { /* never fail the tool call */ }
process.exit(0);
