"""Assessment-based tidy PR suggestion (rule-based).

Collects ``narrow`` assessments with ``tidy_suggestion`` text, scores them
by actionability, and renders a git-friendly YAML+Markdown PR draft.

No LLM calls — purely rule-based scoring so results are deterministic and
work offline.

Typical usage::

    from entirecontext.core.tidy_pr import generate_tidy_pr

    conn = get_db(repo_path)
    print(generate_tidy_pr(conn))
"""

from __future__ import annotations

from datetime import datetime, timezone


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yaml_scalar(value: str) -> str:
    """Single-quote YAML scalar if it contains characters requiring quoting."""
    if any(c in value for c in (":", "#", "'", '"', "\n", "\r")):
        return "'" + value.replace("'", "''") + "'"
    return value


def collect_tidy_suggestions(
    conn,
    *,
    since: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Collect actionable tidy suggestions from narrow assessments.

    Only assessments with ``verdict = 'narrow'`` **and** a non-NULL
    ``tidy_suggestion`` are returned — these are the candidates for a
    follow-up tidy PR.

    Args:
        conn: SQLite connection.
        since: Optional ISO date string; only assessments created on or after
            this date are included.
        limit: Maximum number of results (no limit if ``None``).

    Returns:
        List of dicts with keys ``assessment_id``, ``tidy_suggestion``,
        ``impact_summary``, ``verdict``, and ``feedback``.
    """
    params: list = []
    where_clauses = [
        "verdict = 'narrow'",
        "tidy_suggestion IS NOT NULL",
        "tidy_suggestion != ''",
    ]

    if since is not None:
        where_clauses.append("created_at >= ?")
        params.append(since)

    where_sql = " AND ".join(where_clauses)
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""

    rows = conn.execute(
        f"SELECT id, tidy_suggestion, impact_summary, verdict, feedback "
        f"FROM assessments WHERE {where_sql} ORDER BY created_at DESC{limit_sql}",
        params,
    ).fetchall()

    return [
        {
            "assessment_id": row["id"],
            "tidy_suggestion": row["tidy_suggestion"],
            "impact_summary": row["impact_summary"],
            "verdict": row["verdict"],
            "feedback": row["feedback"],
        }
        for row in rows
    ]


def score_tidy_suggestions(suggestions: list[dict]) -> list[dict]:
    """Score and sort tidy suggestions by actionability.

    Scoring rules (additive):
    - Base score: 1.0 for every suggestion with a ``tidy_suggestion``.
    - +0.5 if the user previously marked the assessment as ``agree``.

    Args:
        suggestions: List of suggestion dicts (from ``collect_tidy_suggestions``).

    Returns:
        Same list with an added ``score`` key, sorted descending by score.
    """
    if not suggestions:
        return []

    scored: list[dict] = []
    for s in suggestions:
        score = 1.0
        if s.get("feedback") == "agree":
            score += 0.5
        scored.append({**s, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def generate_tidy_pr(
    conn,
    *,
    since: str | None = None,
    limit: int = 10,
) -> str:
    """Generate a YAML+Markdown tidy PR draft from narrow assessments.

    Collects and scores ``narrow`` assessments, then renders a PR description
    suitable for committing or sharing with the team.

    Args:
        conn: SQLite connection.
        since: Optional ISO date string; only include assessments from this date.
        limit: Maximum number of suggestions to include (default 10).

    Returns:
        A Markdown string with YAML frontmatter.  If no suggestions are found,
        returns a plain message containing "No tidy suggestions".
    """
    suggestions = collect_tidy_suggestions(conn, since=since, limit=limit)

    if not suggestions:
        return "No tidy suggestions found for the selected range."

    scored = score_tidy_suggestions(suggestions)
    generated_at = _iso_now()

    # --- YAML frontmatter ---
    fm_lines: list[str] = [
        "---",
        "type: tidy-pr",
        f"generated: {_yaml_scalar(generated_at)}",
        f"suggestion_count: {len(scored)}",
    ]
    if since is not None:
        fm_lines.append(f"since: {_yaml_scalar(since)}")
    fm_lines.append("---")
    frontmatter = "\n".join(fm_lines)

    # --- Markdown body ---
    lines: list[str] = [
        frontmatter,
        "",
        "# Tidy PR: Refactor Suggestions",
        "",
        "The following improvements were identified from recent `narrow` assessments.",
        "Each item reduces coupling, simplifies tests, or removes structural debt.",
        "",
        "## Suggested Changes",
        "",
    ]

    for i, s in enumerate(scored, 1):
        suggestion = s["tidy_suggestion"]
        impact = s.get("impact_summary") or ""
        fb = s.get("feedback") or ""
        assessment_id = s.get("assessment_id", "")[:12]

        safe_suggestion = suggestion.replace("\n", " ").replace("\r", "")
        lines.append(f"### {i}. {safe_suggestion}")
        lines.append("")
        if impact:
            lines.append(f"**Impact:** {impact}")
            lines.append("")
        if fb:
            lines.append(f"**Feedback:** {fb}")
            lines.append("")
        lines.append(f"*Assessment: `{assessment_id}`*")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by `ec futures tidy-pr`*")

    return "\n".join(lines)
