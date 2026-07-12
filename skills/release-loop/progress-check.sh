#!/usr/bin/env bash
# Stop hook: warn when .release-loop/progress.md is stale relative to HEAD.
# Outputs nothing when no release-loop is active or progress is current.
set -euo pipefail

PROGRESS=".release-loop/progress.md"
[ -f "$PROGRESS" ] || exit 0

LAST_PROGRESS_SHA=$(git log -1 --format=%H -- "$PROGRESS" 2>/dev/null || true)
[ -n "$LAST_PROGRESS_SHA" ] || exit 0

HEAD_SHA=$(git rev-list -1 HEAD 2>/dev/null || true)
[ -n "$HEAD_SHA" ] || exit 0
[ "$LAST_PROGRESS_SHA" != "$HEAD_SHA" ] || exit 0

COMMITS_SINCE=$(git rev-list --count "${LAST_PROGRESS_SHA}..HEAD" 2>/dev/null || echo 0)

if [ "$COMMITS_SINCE" -ge 1 ]; then
  CURRENT_PHASE=$(grep -m1 '^Phase:' "$PROGRESS" | sed 's/Phase: *//')
  CURRENT_TASKS=$(grep -m1 '^Tasks:' "$PROGRESS" | sed 's/Tasks: *//')
  echo "⚠️ RELEASE-LOOP: progress.md is ${COMMITS_SINCE} commit(s) behind HEAD."
  echo "   Recorded state — Phase: ${CURRENT_PHASE}, Tasks: ${CURRENT_TASKS}"
  echo "   Update .release-loop/progress.md to match actual progress, then commit it."
fi
