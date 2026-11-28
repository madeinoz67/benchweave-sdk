#!/bin/sh
# codanna-mcp.sh — gate the Codanna MCP server on this checkout's code index.
# author: Stephen Eaton
#
# Orca starts the Claude agent at the same moment it starts `scripts.setup`, and
# setup is what writes .codanna/index. A server that starts before that write
# finishes races the indexer and misses Claude Code's MCP startup timeout
# (MCP_TIMEOUT, 30 s by default), so codanna never connects and the nudge points
# the agent at tools that are not there.
#
# setup touches .codanna/setup-in-progress first, then writes
# .codanna/index.ready once the code index is built. This gate waits for that
# marker (bounded), and starts immediately when an index already exists — the
# primary checkout, and a worktree whose setup has already run.
n=0
while [ "$n" -lt 200 ]; do
  [ -f .codanna/index.ready ] && break
  [ -d .codanna/index ] && [ ! -f .codanna/setup-in-progress ] && break
  # No setup and no index: start anyway after a short grace, so a repo without
  # the Orca pack (or a worktree from an older commit) still serves.
  if [ "$n" -ge 20 ] && [ ! -f .codanna/setup-in-progress ] && [ ! -d .codanna/index ]; then break; fi
  sleep 1
  n=$((n + 1))
done
exec codanna --config .codanna/settings.toml serve --watch
