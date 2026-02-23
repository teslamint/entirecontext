"""Futures report generation — team-shareable summaries of assessment trends."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_KNOWN_VERDICTS = ("expand", "narrow", "neutral")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percent(count: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{round(100 * count / total)}%"


def _yaml_scalar(value: str) -> str:
    """Single-quote YAML scalar if it contains characters that require quoting."""
    if any(c in value for c in (":", "#", "'", '"', "\n", "\r")):
        return "'" + value.replace("'", "''") + "'"
    return value


def generate_futures_report(
    assessments: list[dict[str, Any]],
    *,
    project_name: str | None = None,
    since: str | None = None,
) -> str:
    """Generate a Markdown futures report from a list of assessments.

    The document is git-friendly (YAML frontmatter + Markdown sections) and
    suitable for team sharing or committing to the repository.

    Args:
        assessments: List of assessment dicts from ``list_assessments()``.
        project_name: Optional project/repo name for frontmatter.
        since: Optional ISO date string used as the report start bound (label only).

    Returns:
        A UTF-8-safe Markdown string.
    """
    total = len(assessments)
    generated_at = _iso_now()

    # --- YAML frontmatter ---
    fm_lines: list[str] = [
        "---",
        "report: futures",
        f"generated: {generated_at}",
        f"total_assessments: {total}",
    ]
    if project_name is not None:
        fm_lines.append(f"project: {_yaml_scalar(project_name)}")
    if since is not None:
        fm_lines.append(f"since: {_yaml_scalar(since)}")
    fm_lines.append("---")

    # --- Header ---
    title = f"Futures Report — {project_name}" if project_name else "Futures Report"
    body_lines: list[str] = [
        "",
        f"# {title}",
        "",
        f"_Generated {generated_at}_",
        "",
    ]

    if total == 0:
        body_lines += [
            "> No assessments found for the specified period.",
            "",
        ]
        return "\n".join(fm_lines) + "\n" + "\n".join(body_lines)

    # --- Verdict distribution ---
    # Normalise unknown verdicts to "neutral" so the table totals are consistent.
    counts: dict[str, int] = {"expand": 0, "narrow": 0, "neutral": 0}
    for a in assessments:
        v = a.get("verdict", "neutral")
        normalised = v if v in _KNOWN_VERDICTS else "neutral"
        counts[normalised] += 1

    body_lines += [
        "## Verdict Distribution",
        "",
        "| Verdict | Count | % |",
        "|---------|-------|---|",
        f"| 🟢 Expand  | {counts['expand']} | {_percent(counts['expand'], total)} |",
        f"| 🔴 Narrow  | {counts['narrow']} | {_percent(counts['narrow'], total)} |",
        f"| 🟡 Neutral | {counts['neutral']} | {_percent(counts['neutral'], total)} |",
        f"| **Total**  | **{total}** | 100% |",
        "",
    ]

    # --- Assessments detail ---
    body_lines += [
        "## Assessments",
        "",
    ]

    verdict_icons = {"expand": "🟢", "narrow": "🔴", "neutral": "🟡"}

    for a in assessments:
        verdict = a.get("verdict", "neutral")
        icon = verdict_icons.get(verdict, "🟡")
        short_id = (a.get("id") or "")[:8]
        created = (a.get("created_at") or "")[:10]
        impact = a.get("impact_summary") or ""
        alignment = a.get("roadmap_alignment")
        suggestion = a.get("tidy_suggestion")
        feedback = a.get("feedback")
        feedback_reason = a.get("feedback_reason")
        model = a.get("model_name")

        body_lines.append(f"### {icon} {impact or short_id}")
        body_lines.append("")
        body_lines.append(f"- **Verdict:** {verdict}  ")
        body_lines.append(f"- **ID:** `{short_id}`  ")
        body_lines.append(f"- **Date:** {created}  ")
        if model:
            body_lines.append(f"- **Model:** {model}  ")
        body_lines.append("")
        if alignment:
            body_lines.append(f"**Roadmap alignment:** {alignment}")
            body_lines.append("")
        if suggestion:
            body_lines.append(f"**Tidy suggestion:** {suggestion}")
            body_lines.append("")
        if feedback:
            feedback_icon = "✅" if feedback == "agree" else "❌"
            fb_line = f"**Feedback:** {feedback_icon} {feedback}"
            if feedback_reason:
                fb_line += f" — {feedback_reason}"
            body_lines.append(fb_line)
            body_lines.append("")
        body_lines.append("---")
        body_lines.append("")

    # --- Feedback summary ---
    feedbacked = [a for a in assessments if a.get("feedback")]
    if feedbacked:
        agree_count = sum(1 for a in feedbacked if a.get("feedback") == "agree")
        disagree_count = len(feedbacked) - agree_count
        body_lines += [
            "## Feedback Summary",
            "",
            f"- **Reviewed:** {len(feedbacked)} / {total}",
            f"- **Agree:** {agree_count}",
            f"- **Disagree:** {disagree_count}",
            "",
        ]

    return "\n".join(fm_lines) + "\n" + "\n".join(body_lines)
