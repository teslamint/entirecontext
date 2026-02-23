"""Team dashboard — aggregate stats for sessions, checkpoints, and assessments.

Queries existing DB tables to produce a single summary dict suitable for
rendering in a terminal dashboard or exporting as a report.

No external dependencies — pure SQLite queries against existing tables.

Typical usage::

    from entirecontext.core.dashboard import get_dashboard_stats

    conn = get_db(repo_path)
    stats = get_dashboard_stats(conn, since="2025-01-01")
"""

from __future__ import annotations


def get_dashboard_stats(
    conn,
    *,
    since: str | None = None,
    limit: int = 10,
) -> dict:
    """Collect aggregate stats across sessions, checkpoints, and assessments.

    Args:
        conn: SQLite connection.
        since: Optional ISO date string; only include records on or after this
            date (inclusive). Applied to ``started_at`` for sessions,
            ``created_at`` for checkpoints and assessments.
        limit: Maximum number of recent rows to include per section (default 10).

    Returns:
        A dict with the following structure::

            {
                "sessions": {
                    "total": int,
                    "active": int,      # ended_at IS NULL
                    "ended": int,       # ended_at IS NOT NULL
                    "recent": list[dict],   # up to `limit` most recent
                },
                "checkpoints": {
                    "total": int,
                    "recent": list[dict],
                },
                "assessments": {
                    "total": int,
                    "by_verdict": {"expand": int, "narrow": int, "neutral": int},
                    "with_feedback": int,
                    "feedback_rate": float,  # 0.0 if total == 0
                    "recent": list[dict],
                },
                "since": str | None,   # echoed from argument
                "limit": int,          # echoed from argument
            }
    """
    since_params: list = [since] if since is not None else []
    since_clause = " WHERE started_at >= ?" if since is not None else ""
    since_clause_ca = " WHERE created_at >= ?" if since is not None else ""

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    row = conn.execute(
        f"SELECT COUNT(*) AS total,"
        f" SUM(CASE WHEN ended_at IS NULL THEN 1 ELSE 0 END) AS active,"
        f" SUM(CASE WHEN ended_at IS NOT NULL THEN 1 ELSE 0 END) AS ended"
        f" FROM sessions{since_clause}",
        since_params,
    ).fetchone()

    sessions_total = row["total"] or 0
    sessions_active = row["active"] or 0
    sessions_ended = row["ended"] or 0

    recent_sessions_params = since_params + [limit]
    recent_sessions_where = since_clause if since is not None else ""
    recent_sessions = conn.execute(
        f"SELECT id, session_title, started_at, last_activity_at, ended_at"
        f" FROM sessions{recent_sessions_where}"
        f" ORDER BY last_activity_at DESC LIMIT ?",
        recent_sessions_params,
    ).fetchall()

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------
    ckp_row = conn.execute(
        f"SELECT COUNT(*) AS total FROM checkpoints{since_clause_ca}",
        since_params,
    ).fetchone()
    checkpoints_total = ckp_row["total"] or 0

    recent_ckp_params = since_params + [limit]
    recent_ckp_where = since_clause_ca if since is not None else ""
    recent_checkpoints = conn.execute(
        f"SELECT id, session_id, git_branch, git_commit_hash, created_at"
        f" FROM checkpoints{recent_ckp_where}"
        f" ORDER BY created_at DESC LIMIT ?",
        recent_ckp_params,
    ).fetchall()

    # ------------------------------------------------------------------
    # Assessments
    # ------------------------------------------------------------------
    asmt_row = conn.execute(
        f"SELECT COUNT(*) AS total,"
        f" SUM(CASE WHEN verdict='expand' THEN 1 ELSE 0 END) AS expand_count,"
        f" SUM(CASE WHEN verdict='narrow' THEN 1 ELSE 0 END) AS narrow_count,"
        f" SUM(CASE WHEN verdict='neutral' THEN 1 ELSE 0 END) AS neutral_count,"
        f" SUM(CASE WHEN feedback IS NOT NULL THEN 1 ELSE 0 END) AS with_feedback"
        f" FROM assessments{since_clause_ca}",
        since_params,
    ).fetchone()

    asmt_total = asmt_row["total"] or 0
    asmt_expand = asmt_row["expand_count"] or 0
    asmt_narrow = asmt_row["narrow_count"] or 0
    asmt_neutral = asmt_row["neutral_count"] or 0
    asmt_feedback = asmt_row["with_feedback"] or 0
    feedback_rate = asmt_feedback / asmt_total if asmt_total > 0 else 0.0

    recent_asmt_params = since_params + [limit]
    recent_asmt_where = since_clause_ca if since is not None else ""
    recent_assessments = conn.execute(
        f"SELECT id, verdict, impact_summary, feedback, created_at"
        f" FROM assessments{recent_asmt_where}"
        f" ORDER BY created_at DESC LIMIT ?",
        recent_asmt_params,
    ).fetchall()

    return {
        "sessions": {
            "total": sessions_total,
            "active": sessions_active,
            "ended": sessions_ended,
            "recent": [dict(r) for r in recent_sessions],
        },
        "checkpoints": {
            "total": checkpoints_total,
            "recent": [dict(r) for r in recent_checkpoints],
        },
        "assessments": {
            "total": asmt_total,
            "by_verdict": {
                "expand": asmt_expand,
                "narrow": asmt_narrow,
                "neutral": asmt_neutral,
            },
            "with_feedback": asmt_feedback,
            "feedback_rate": feedback_rate,
            "recent": [dict(r) for r in recent_assessments],
        },
        "since": since,
        "limit": limit,
    }
