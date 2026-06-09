# 0003. sessions_ended Non-Monotonic Behavior — Won't-Fix

**Status:** accepted
**Date:** 2026-06-09

## Context

Dashboard maturity rates (`retrieval_assisted_session_rate`, `applied_context_rate`) use
`sessions_ended` (count of sessions with `ended_at IS NOT NULL`) as denominator. If this
count can decrease between measurements, rates become non-monotonic and harder to interpret.

Deferred from v0.8.1 and v0.9.0 for evaluation.

## Investigation

One code path resets `ended_at` to NULL: `codex_ingest.py:335`. When a Codex notify event
delivers new turns to an already-ended session, the session reopens (`ended_at = NULL`) to
accept the turns. The session is re-closed by `close_stale_sessions()` after the configured
idle timeout (default 60 minutes).

Claude Code sessions (the primary session type) never reset `ended_at` — `session_lifecycle.py`
resume path updates `last_activity_at` only.

## Decision

Won't-fix. The transient decrease is:

- **Scoped:** Codex sessions only, which are a minority of total sessions.
- **Self-healing:** idle timeout re-closes the session within minutes to hours.
- **Low impact:** dashboard snapshots are point-in-time; the transient dip does not accumulate.

Fixing would require either (a) creating a new session instead of reopening, which breaks
Codex session continuity, or (b) appending turns without resetting `ended_at`, which breaks
the "active session" invariant for codex sessions receiving new data.

## Consequences

- Maturity rates may show minor fluctuation during active Codex ingestion periods.
- No code change needed. If Codex session volume grows significantly, revisit this decision.
