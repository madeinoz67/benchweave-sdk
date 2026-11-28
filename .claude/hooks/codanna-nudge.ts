#!/usr/bin/env bun
// codanna-nudge.ts — PostToolUse, one advisory per session.
//
// The "use Codanna before rg or grep" rule is prose, and prose loses to the default tool
// at the moment of a search. This fires once when a session reaches for rg, grep or Grep
// in a Codanna-indexed repo and has not used Codanna yet, then never again. PostToolUse
// exit 2 with stderr is the channel this repo already uses to reach the model
// (see ledger-guard.mjs); it cannot block a call.
//
// A nudge that nags is a hook people disable, so: once per session, and never for a
// tool that is not a search.
// author: Stephen Eaton

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

type HookEvent = {
  cwd?: string;
  session_id?: string;
  tool_name?: string;
  tool_input?: { command?: string };
};

type SessionState = { codanna: boolean; nudged: boolean };

const NUDGE = [
  "",
  "Codanna nudge: this repo is indexed, and this session has not used Codanna yet.",
  'For symbol and "where is X" lookups, use Codanna before rg, grep or reading whole files:',
  "  main session: mcp__codanna__semantic_search_with_context, find_symbol, analyze_impact",
  '  worktree or subagent: codanna mcp semantic_search_with_context query:"..." limit:5 --json',
  "rg stays right for exact strings, HTML, CSS, templates and config keys.",
  "",
].join("\n");

function markerPath(sessionId: string | undefined): string {
  const dir = join(tmpdir(), "claude-codanna-nudge");
  try {
    mkdirSync(dir, { recursive: true });
  } catch {
    // no marker means we nudge again; that is survivable
  }
  return join(dir, `${sessionId || "unknown"}.json`);
}

function load(path: string): SessionState {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as SessionState;
  } catch {
    return { codanna: false, nudged: false };
  }
}

function save(path: string, state: SessionState): void {
  try {
    writeFileSync(path, JSON.stringify(state));
  } catch {
    // a nudge is never worth failing a tool call over
  }
}

async function main(): Promise<number> {
  let event: HookEvent;
  try {
    event = (await Bun.stdin.json()) as HookEvent;
  } catch {
    return 0;
  }

  const cwd = event.cwd ?? process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
  if (!existsSync(join(cwd, ".codanna", "settings.toml"))) return 0;

  const path = markerPath(event.session_id);
  const state = load(path);
  const tool = String(event.tool_name ?? "");
  const command = String(event.tool_input?.command ?? "");

  // Any Codanna call disarms the nudge for the rest of the session. Both surfaces
  // count: the MCP tools in the main session, and the CLI, which is the ONLY route
  // for worktree subagents that cannot call mcp__codanna__* at all. Matching the
  // command matters here — the tool name for a CLI call is just "Bash".
  const isCodannaCall = tool.startsWith("mcp__codanna__") || /(?:^|&&|;|\|\|)\s*codanna\b/.test(command);
  if (isCodannaCall) {
    if (!state.codanna) save(path, { ...state, codanna: true });
    return 0;
  }

  if (state.codanna || state.nudged) return 0;

  const isSearch =
    tool === "Grep" || (tool === "Bash" && /^\s*(rg|grep)\b/.test(command));
  if (!isSearch) return 0;

  save(path, { codanna: false, nudged: true });
  process.stderr.write(NUDGE);
  return 2;
}

process.exit(await main());
