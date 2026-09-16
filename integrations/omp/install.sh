#!/usr/bin/env bash
# Install the EntireContext omp plugin via `omp plugin link` (extension +
# .mcp.json discovery in one step; see plugin-manager-installer-plumbing.md:
# "conventional discovery scans ... .mcp.json under enabled npm/link plugin
# roots"). A symlink, so local edits to extension/index.ts take effect after
# restarting omp — no reinstall needed.
#
# A pre-existing native extension at <agent-dir>/extensions/entirecontext
# (from manually copying extension/index.ts there) is a SEPARATE file the
# runtime does not deduplicate against the linked plugin, so every hook would
# fire twice. It is always backed up and removed as a prerequisite, moved
# OUTSIDE extensions/ so the one-level directory scan can't pick it back up.
#
# Usage: ./install.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.omp/agent}"
LEGACY_EXTENSION_DIR="$AGENT_DIR/extensions/entirecontext"
BACKUP_ROOT="$AGENT_DIR/extensions-backup"

if ! command -v omp >/dev/null 2>&1; then
  echo "omp CLI not found on PATH; install omp first." >&2
  exit 1
fi

if [[ -e "$LEGACY_EXTENSION_DIR" || -L "$LEGACY_EXTENSION_DIR" ]]; then
  mkdir -p "$BACKUP_ROOT"
  backup="$BACKUP_ROOT/entirecontext-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$LEGACY_EXTENSION_DIR" "$backup"
  echo "Removed legacy native extension (would double-fire hooks): $LEGACY_EXTENSION_DIR -> $backup" >&2
fi

omp plugin link "$SRC_DIR"

remaining=$(find "$AGENT_DIR/extensions" -maxdepth 1 -iname 'entirecontext*' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$remaining" != "0" ]]; then
  echo "WARNING: $remaining entry/entries named entirecontext* still under $AGENT_DIR/extensions — check for a second install." >&2
fi

echo "Linked via 'omp plugin link'. Verify with: omp plugin list"
echo "Restart omp (or start a new session) for the extension and MCP server to load."
