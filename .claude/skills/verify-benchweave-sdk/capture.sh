#!/usr/bin/env bash
# capture.sh — run one benchweave-sdk command and record exit, stdout and stderr.
#
# usage: capture.sh <evidence-dir> <name> -- <sdk args...>
#
# Resolves the repo root from this script's own location, sets the venv the
# checkout uses, and always runs with --no-sync so the environment is not
# re-resolved under the command being measured. Appends "<name>\t<exit>" to
# <evidence-dir>/transcript.tsv and exits with the command's own exit code.
set -uo pipefail

if [ "$#" -lt 4 ] || [ "${3:-}" != "--" ]; then
  echo "usage: $0 <evidence-dir> <name> -- <sdk args...>" >&2
  exit 64
fi

EV="$1"
NAME="$2"
shift 3

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
mkdir -p "$EV"

(
  cd "$REPO" || exit 70
  UV_PROJECT_ENVIRONMENT=venv uv run --no-sync benchweave-sdk "$@"
) >"$EV/$NAME.stdout" 2>"$EV/$NAME.stderr"

code=$?
printf '%s\n' "$code" >"$EV/$NAME.exit"
printf '%s\t%s\n' "$NAME" "$code" >>"$EV/transcript.tsv"
exit "$code"
