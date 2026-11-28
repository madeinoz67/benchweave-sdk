#!/bin/sh
# codanna-mcp.sh — gate the Codanna MCP server on this checkout's code index.
# author: Stephen Eaton
#
# Orca starts the Claude agent and `scripts.setup` at the same time, and setup is
# what writes .codanna/index. A server that starts before that write finishes
# races the indexer (Tantivy LockBusy) and misses the MCP startup timeout
# (MCP_TIMEOUT, 30 s by default), so codanna never connects and the nudge points
# the agent at tools that are not there.
#
# In a primary checkout (.git is a directory) the index already exists: serve
# immediately. In a worktree (.git is a file) wait for setup's ready marker,
# written after the code index. A worktree created outside Orca never announces
# itself; after 20 s with no setup flag, serve and let it build the index.
if [ -d .git ]; then
  exec codanna --config .codanna/settings.toml serve --watch
fi

n=0
announced=0
while [ "$n" -lt 200 ] && [ ! -f .codanna/index.ready ]; do
  [ -f .codanna/setup-in-progress ] && announced=1
  if [ "$n" -ge 20 ] && [ "$announced" -eq 0 ]; then break; fi
  sleep 1
  n=$((n + 1))
done
exec codanna --config .codanna/settings.toml serve --watch
