"""After-Action Report (AAR) generation for session-end telemetry."""

from __future__ import annotations

import datetime
import sqlite3
from typing import Any


def generate_aar(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Pure query function — returns structured AAR dict, no side effects."""
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    extracted_count = conn.execute(
        "SELECT COUNT(*) FROM decision_candidates WHERE session_id = ? AND review_status = 'confirmed'",
        (session_id,),
    ).fetchone()[0]

    extracted_titles: list[str] = []
    if extracted_count > 0:
        rows = conn.execute(
            """
            SELECT d.title
            FROM decision_candidates dc
            JOIN decisions d ON d.id = dc.promoted_decision_id
            WHERE dc.session_id = ? AND dc.review_status = 'confirmed'
              AND dc.promoted_decision_id IS NOT NULL
            """,
            (session_id,),
        ).fetchall()
        extracted_titles = [r["title"] for r in rows]

    surfaced_count = conn.execute(
        "SELECT COUNT(DISTINCT result_id) FROM retrieval_selections WHERE session_id = ? AND result_type = 'decision'",
        (session_id,),
    ).fetchone()[0]

    surfaced_titles: list[str] = []
    if surfaced_count > 0:
        rows = conn.execute(
            """
            SELECT DISTINCT d.title
            FROM retrieval_selections rs
            JOIN decisions d ON d.id = rs.result_id
            WHERE rs.session_id = ? AND rs.result_type = 'decision'
            """,
            (session_id,),
        ).fetchall()
        surfaced_titles = [r["title"] for r in rows]

    applied_count = conn.execute(
        """
        SELECT COUNT(DISTINCT rs.result_id) FROM context_applications ca
        JOIN retrieval_selections rs ON rs.id = ca.retrieval_selection_id
        WHERE rs.session_id = ? AND rs.result_type = 'decision'
        """,
        (session_id,),
    ).fetchone()[0]

    pdi_rate = applied_count / surfaced_count if surfaced_count > 0 else 0.0

    new_assessments = conn.execute(
        """
        SELECT COUNT(*) FROM assessments a
        JOIN checkpoints c ON a.checkpoint_id = c.id
        WHERE c.session_id = ?
        """,
        (session_id,),
    ).fetchone()[0]

    return {
        "session_id": session_id,
        "generated_at": generated_at,
        "decisions_extracted": {
            "count": extracted_count,
            "titles": extracted_titles,
            "note": "(extraction worker may still be running)",
        },
        "decisions_surfaced": {
            "count": surfaced_count,
            "titles": surfaced_titles,
        },
        "pdi_delta": {
            "surfaced": surfaced_count,
            "applied": applied_count,
            "rate": pdi_rate,
        },
        "assessments": {
            "new_count": new_assessments,
        },
    }


def format_aar_summary(aar: dict[str, Any]) -> str:
    """Human-readable AAR text for hook stdout."""
    sid_short = aar["session_id"][:8]
    extracted = aar["decisions_extracted"]
    surfaced = aar["decisions_surfaced"]
    pdi = aar["pdi_delta"]
    assessments = aar["assessments"]

    rate_pct = f"{pdi['rate'] * 100:.1f}%"
    pdi_line = (
        f"{pdi['applied']}/{pdi['surfaced']} applied ({rate_pct})" if pdi["surfaced"] > 0 else "no decisions surfaced"
    )

    lines = [
        f"[EntireContext AAR] Session {sid_short}",
        f"  Decisions extracted: {extracted['count']} {extracted['note']}",
        f"  Decisions surfaced: {surfaced['count']}",
        f"  PDI delta: {pdi_line}",
        f"  Assessments created: {assessments['new_count']}",
    ]
    return "\n".join(lines)
