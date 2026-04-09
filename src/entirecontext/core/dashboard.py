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
    turns_since_clause = " WHERE s.started_at >= ?" if since is not None else ""

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

    turns_row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN t.files_touched IS NOT NULL AND TRIM(t.files_touched) NOT IN ('', '[]') THEN 1 ELSE 0 END) AS with_files"
        " FROM turns t"
        " JOIN sessions s ON t.session_id = s.id"
        f"{turns_since_clause}",
        since_params,
    ).fetchone()
    turns_total = turns_row["total"] or 0
    turns_with_files = turns_row["with_files"] or 0

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

    anchored_assessment_count = conn.execute(
        "SELECT COUNT(*) AS total FROM assessments WHERE checkpoint_id IS NOT NULL"
        + (" AND created_at >= ?" if since is not None else ""),
        since_params,
    ).fetchone()["total"] or 0
    checkpoint_anchored_assessment_rate = anchored_assessment_count / asmt_total if asmt_total > 0 else 0.0

    retrieval_events_total = conn.execute(
        f"SELECT COUNT(*) AS total FROM retrieval_events{since_clause_ca}",
        since_params,
    ).fetchone()["total"] or 0
    retrieval_sessions_row = conn.execute(
        "SELECT COUNT(DISTINCT session_id) AS total FROM retrieval_events"
        + (" WHERE created_at >= ?" if since is not None else ""),
        since_params,
    ).fetchone()
    retrieval_sessions_total = retrieval_sessions_row["total"] or 0

    retrieval_selections_total = conn.execute(
        f"SELECT COUNT(*) AS total FROM retrieval_selections{since_clause_ca}",
        since_params,
    ).fetchone()["total"] or 0

    applications_row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN retrieval_selection_id IS NOT NULL THEN 1 ELSE 0 END) AS with_selection,"
        " SUM(CASE WHEN source_type IN ('assessment', 'lesson') THEN 1 ELSE 0 END) AS lesson_reuse"
        f" FROM context_applications{since_clause_ca}",
        since_params,
    ).fetchone()
    context_applications_total = applications_row["total"] or 0
    context_applications_with_selection = applications_row["with_selection"] or 0
    lesson_reuse_count = applications_row["lesson_reuse"] or 0

    retrieval_assisted_session_rate = retrieval_sessions_total / sessions_total if sessions_total > 0 else 0.0
    search_to_selection_rate = retrieval_selections_total / retrieval_events_total if retrieval_events_total > 0 else 0.0
    applied_context_rate = (
        context_applications_with_selection / retrieval_selections_total if retrieval_selections_total > 0 else 0.0
    )
    lesson_reuse_rate = lesson_reuse_count / context_applications_total if context_applications_total > 0 else 0.0

    changed_ended_sessions = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM sessions s
        WHERE s.ended_at IS NOT NULL
          {since_filter}
          AND (
              EXISTS (
                  SELECT 1
                  FROM turns t
                  WHERE t.session_id = s.id
                    AND (
                        (t.files_touched IS NOT NULL AND TRIM(t.files_touched) NOT IN ('', '[]'))
                        OR (t.git_commit_hash IS NOT NULL AND TRIM(t.git_commit_hash) != '')
                    )
              )
              OR EXISTS (
                  SELECT 1 FROM checkpoints c WHERE c.session_id = s.id
              )
          )
        """.format(since_filter="AND s.started_at >= ?" if since is not None else ""),
        since_params,
    ).fetchone()["total"] or 0
    changed_ended_sessions_with_checkpoints = conn.execute(
        """
        SELECT COUNT(DISTINCT s.id) AS total
        FROM sessions s
        JOIN checkpoints c ON c.session_id = s.id
        WHERE s.ended_at IS NOT NULL
          {since_filter}
          AND (
              EXISTS (
                  SELECT 1
                  FROM turns t
                  WHERE t.session_id = s.id
                    AND (
                        (t.files_touched IS NOT NULL AND TRIM(t.files_touched) NOT IN ('', '[]'))
                        OR (t.git_commit_hash IS NOT NULL AND TRIM(t.git_commit_hash) != '')
                    )
              )
              OR EXISTS (
                  SELECT 1 FROM checkpoints c2 WHERE c2.session_id = s.id
              )
          )
        """.format(since_filter="AND s.started_at >= ?" if since is not None else ""),
        since_params,
    ).fetchone()["total"] or 0
    checkpoint_coverage_rate = (
        changed_ended_sessions_with_checkpoints / changed_ended_sessions if changed_ended_sessions > 0 else 0.0
    )

    avg_turns_per_session = turns_total / sessions_total if sessions_total > 0 else 0.0
    turns_with_files_rate = turns_with_files / turns_total if turns_total > 0 else 0.0

    capture_score = 0
    if sessions_total > 0:
        capture_score += 5
    if avg_turns_per_session >= 2:
        capture_score += 5
    if turns_with_files_rate >= 0.25:
        capture_score += 8
    if checkpoint_coverage_rate >= 0.5:
        capture_score += 12

    distill_score = 0
    if asmt_total > 0:
        distill_score += 5
    if feedback_rate >= 0.5:
        distill_score += 8
    if asmt_feedback > 0:
        distill_score += 5
    if checkpoint_anchored_assessment_rate >= 0.5:
        distill_score += 7

    retrieve_score = 0
    if retrieval_events_total > 0:
        retrieve_score += 5
    if retrieval_assisted_session_rate >= 0.25:
        retrieve_score += 8
    if search_to_selection_rate >= 0.25:
        retrieve_score += 12

    intervene_score = 0
    if context_applications_total > 0:
        intervene_score += 5
    if applied_context_rate >= 0.1:
        intervene_score += 8
    if lesson_reuse_rate >= 0.2:
        intervene_score += 7

    maturity_score = capture_score + distill_score + retrieve_score + intervene_score
    if maturity_score >= 75:
        maturity_grade = "Closed Loop"
    elif maturity_score >= 50:
        maturity_grade = "Operational"
    elif maturity_score >= 25:
        maturity_grade = "Partial"
    else:
        maturity_grade = "Absent"

    return {
        "sessions": {
            "total": sessions_total,
            "active": sessions_active,
            "ended": sessions_ended,
            "recent": [dict(r) for r in recent_sessions],
            "avg_turns_per_session": avg_turns_per_session,
        },
        "checkpoints": {
            "total": checkpoints_total,
            "recent": [dict(r) for r in recent_checkpoints],
            "changed_ended_sessions": changed_ended_sessions,
            "changed_ended_sessions_with_checkpoints": changed_ended_sessions_with_checkpoints,
            "checkpoint_coverage_rate": checkpoint_coverage_rate,
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
            "with_checkpoint": anchored_assessment_count,
            "checkpoint_anchored_assessment_rate": checkpoint_anchored_assessment_rate,
            "recent": [dict(r) for r in recent_assessments],
        },
        "telemetry": {
            "retrieval_events": {
                "total": retrieval_events_total,
                "sessions_with_retrieval": retrieval_sessions_total,
            },
            "retrieval_selections": {
                "total": retrieval_selections_total,
            },
            "context_applications": {
                "total": context_applications_total,
                "with_selection": context_applications_with_selection,
            },
            "rates": {
                "retrieval_assisted_session_rate": retrieval_assisted_session_rate,
                "search_to_selection_rate": search_to_selection_rate,
                "applied_context_rate": applied_context_rate,
                "lesson_reuse_rate": lesson_reuse_rate,
                "checkpoint_anchored_assessment_rate": checkpoint_anchored_assessment_rate,
                "turns_with_files_rate": turns_with_files_rate,
            },
        },
        "maturity_breakdown": {
            "capture": capture_score,
            "distill": distill_score,
            "retrieve": retrieve_score,
            "intervene": intervene_score,
        },
        "maturity_score": maturity_score,
        "maturity_grade": maturity_grade,
        "since": since,
        "limit": limit,
    }
