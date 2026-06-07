from __future__ import annotations

import re
import sqlite3

_EXPAND_RE = re.compile(r"^feat[\s(:]", re.IGNORECASE)
_NARROW_RE = re.compile(r"^revert[\s(:]", re.IGNORECASE)


def compute_rule_verdict(commit_messages: list[str]) -> str:
    has_expand = any(_EXPAND_RE.match(m.strip()) for m in commit_messages)
    has_narrow = any(_NARROW_RE.match(m.strip()) for m in commit_messages)
    if has_expand and has_narrow:
        return "neutral"
    if has_expand:
        return "expand"
    if has_narrow:
        return "narrow"
    return "neutral"


def auto_assess_checkpoint(
    conn: sqlite3.Connection, checkpoint_id: str, repo_path: str, session_id: str
) -> dict | None:
    """Create a rule-based assessment for a checkpoint. Never raises."""
    try:
        from .futures import create_assessment
        from .git_utils import get_commit_messages

        row = conn.execute(
            "SELECT git_commit_hash, diff_summary FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if not row:
            return None
        to_commit = row["git_commit_hash"]

        from_commit = None
        pred = conn.execute(
            "SELECT git_commit_hash FROM checkpoints"
            " WHERE session_id = ? AND rowid < (SELECT rowid FROM checkpoints WHERE id = ?)"
            " ORDER BY rowid DESC LIMIT 1",
            (session_id, checkpoint_id),
        ).fetchone()
        if pred:
            from_commit = pred["git_commit_hash"]

        if not from_commit:
            # Fallback: session metadata start_git_commit
            import json

            session_row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session_row and session_row["metadata"]:
                try:
                    meta = (
                        json.loads(session_row["metadata"])
                        if isinstance(session_row["metadata"], str)
                        else session_row["metadata"]
                    )
                    from_commit = meta.get("start_git_commit")
                except Exception:
                    pass

        messages = get_commit_messages(repo_path, from_commit, to_commit)
        verdict = compute_rule_verdict(messages)

        impact = messages[0][:120] if messages else "Auto-assessed checkpoint"

        return create_assessment(
            conn,
            checkpoint_id=checkpoint_id,
            verdict=verdict,
            impact_summary=impact,
            diff_summary=row["diff_summary"],
            model_name="rule-based",
        )
    except Exception:
        return None


def backfill_unassessed_checkpoints(
    conn: sqlite3.Connection, repo_path: str, session_id: str | None = None, window_days: int = 7
) -> int:
    query = """
        SELECT c.id, c.session_id FROM checkpoints c
        LEFT JOIN assessments a ON a.checkpoint_id = c.id
        WHERE a.id IS NULL AND c.created_at >= datetime('now', ?)
    """
    params: list = [f"-{window_days} days"]
    if session_id:
        query += " AND c.session_id = ?"
        params.append(session_id)
    query += " LIMIT 50"

    rows = conn.execute(query, params).fetchall()
    count = 0
    for row in rows:
        result = auto_assess_checkpoint(conn, row["id"], repo_path, row["session_id"])
        if result:
            count += 1
    return count


def get_enrichment_candidates(
    conn: sqlite3.Connection, session_id: str | None = None, window_days: int = 7, limit: int = 10
) -> list[dict]:
    query = """
        SELECT a.id, a.checkpoint_id, a.verdict, a.model_name, a.impact_summary,
               c.git_commit_hash, c.diff_summary, c.session_id
        FROM assessments a
        JOIN checkpoints c ON a.checkpoint_id = c.id
        WHERE a.model_name = 'rule-based' AND a.created_at >= datetime('now', ?)
    """
    params: list = [f"-{window_days} days"]
    if session_id:
        query += " AND c.session_id = ?"
        params.append(session_id)
    query += " ORDER BY a.created_at DESC LIMIT ?"
    params.append(limit)

    return [dict(row) for row in conn.execute(query, params).fetchall()]


def enrich_assessment(conn: sqlite3.Connection, assessment: dict, repo_path: str, config: dict) -> bool:
    try:
        import json

        from .futures import ASSESS_SYSTEM_PROMPT, VALID_VERDICTS, add_feedback
        from .llm import get_backend, strip_markdown_fences

        futures_config = config["futures"]
        backend_key = futures_config["default_backend"]
        backend = get_backend(backend_key, futures_config.get("default_model"))
        user_prompt = (
            f"Repository path: {repo_path}\n"
            f"Rule-based verdict: {assessment.get('verdict', 'neutral')}\n"
            f"Rule-based impact summary: {assessment.get('impact_summary') or ''}\n"
            f"Diff summary:\n{assessment.get('diff_summary') or ''}"
        )
        response = backend.complete(ASSESS_SYSTEM_PROMPT, user_prompt)
        payload = json.loads(strip_markdown_fences(response))

        original_verdict = assessment["verdict"]
        new_verdict = payload.get("verdict", original_verdict)
        if new_verdict not in VALID_VERDICTS:
            new_verdict = original_verdict

        impact_summary = payload.get("impact_summary", assessment.get("impact_summary"))
        roadmap_alignment = payload.get("roadmap_alignment", assessment.get("roadmap_alignment"))
        tidy_suggestion = payload.get("tidy_suggestion", assessment.get("tidy_suggestion"))
        backend_name = f"{backend_key}-cli"

        conn.execute(
            """
            UPDATE assessments
            SET verdict = ?, impact_summary = ?, roadmap_alignment = ?, tidy_suggestion = ?, model_name = ?
            WHERE id = ?
            """,
            (
                new_verdict,
                impact_summary,
                roadmap_alignment,
                tidy_suggestion,
                backend_name,
                assessment["id"],
            ),
        )

        if new_verdict == original_verdict:
            add_feedback(conn, assessment["id"], "agree", "auto:llm-confirmed")
        else:
            add_feedback(conn, assessment["id"], "disagree", f"auto:revised:{original_verdict}->{new_verdict}")
        return True
    except Exception:
        return False


def apply_git_evidence_feedback(
    conn: sqlite3.Connection, repo_path: str, session_id: str | None = None, window_days: int = 7
) -> int:
    try:
        from .futures import add_feedback
        from .git_utils import get_commit_messages

        query = """
            SELECT a.id, a.checkpoint_id, c.git_commit_hash
            FROM assessments a
            JOIN checkpoints c ON a.checkpoint_id = c.id
            WHERE a.feedback IS NULL
              AND a.model_name = 'rule-based'
              AND a.created_at >= datetime('now', ?)
        """
        params: list = [f"-{window_days} days"]
        if session_id:
            query += " AND c.session_id = ?"
            params.append(session_id)
        query += " LIMIT 50"

        rows = conn.execute(query, params).fetchall()
        count = 0
        for row in rows:
            messages = get_commit_messages(repo_path, row["git_commit_hash"], "HEAD")
            if messages:
                add_feedback(conn, row["id"], "agree", feedback_reason="auto:committed")
                count += 1
        return count
    except Exception:
        return 0


def compute_verdict_accuracy(conn: sqlite3.Connection) -> dict:
    rule_count = conn.execute(
        "SELECT COUNT(*) FROM assessments WHERE model_name = 'rule-based'"
    ).fetchone()[0]

    enriched_rows = conn.execute(
        "SELECT verdict, feedback FROM assessments"
        " WHERE model_name IS NOT NULL AND model_name != 'rule-based'"
        " AND feedback IS NOT NULL"
    ).fetchall()

    if not enriched_rows:
        return {
            "total_rule_based": rule_count,
            "total_enriched": 0,
            "agreement_rate": None,
            "per_verdict": {},
        }

    per_verdict: dict[str, dict[str, int]] = {}
    agree_count = 0
    for row in enriched_rows:
        verdict = row["verdict"]
        feedback = row["feedback"]
        if verdict not in per_verdict:
            per_verdict[verdict] = {"agree": 0, "disagree": 0}
        if feedback == "agree":
            per_verdict[verdict]["agree"] += 1
            agree_count += 1
        elif feedback == "disagree":
            per_verdict[verdict]["disagree"] += 1

    total = len(enriched_rows)
    return {
        "total_rule_based": rule_count,
        "total_enriched": total,
        "agreement_rate": agree_count / total if total > 0 else None,
        "per_verdict": per_verdict,
    }
