#!/usr/bin/env bun
// codanna-archive.ts — Orca scripts.archive: stop any Codanna server still bound to
// this worktree before Orca deletes it. The index lives inside the worktree and is
// removed with it.
// author: Stephen Eaton

import { existsSync, readlinkSync, realpathSync } from "node:fs";
import { sep } from "node:path";

const wtRaw = process.env.ORCA_WORKTREE_PATH || process.cwd();
const wt = existsSync(wtRaw) ? realpathSync(wtRaw) : wtRaw;

function out(cmd: string[]): string {
  if (!Bun.which(cmd[0])) return "";
  const p = Bun.spawnSync(cmd, { stdout: "pipe", stderr: "ignore" });
  return p.exitCode === 0 ? p.stdout.toString() : "";
}

function cwdOf(pid: number): string {
  const proc = `/proc/${pid}/cwd`;
  if (existsSync(proc)) {
    try { return readlinkSync(proc); } catch { return ""; }
  }
  // macOS: lsof prints the cwd as an "n<path>" field
  const line = out(["lsof", "-a", "-p", String(pid), "-d", "cwd", "-Fn"])
    .split("\n").find((l) => l.startsWith("n"));
  return line ? line.slice(1) : "";
}

try {
  const pids = out(["pgrep", "-f", "codanna.*serve"]).split(/\s+/).filter(Boolean).map(Number);
  for (const pid of pids) {
    if (pid === process.pid) continue;
    const cwd = cwdOf(pid);
    if (cwd && (cwd === wt || cwd.startsWith(wt + sep))) {
      try { process.kill(pid, "SIGTERM"); process.stderr.write(`codanna-archive: stopped codanna serve pid ${pid}\n`); }
      catch { /* already gone */ }
    }
  }
} catch { /* never block deletion */ }
process.exit(0);
