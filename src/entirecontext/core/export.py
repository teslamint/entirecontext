"""Markdown export for sessions — git-friendly sharing format."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yaml_scalar(value: str) -> str:
    """Wrap a string value in YAML single-quotes if it contains special chars."""
    if any(c in value for c in (":", "#", "'", "\n", "\r")):
        return "'" + value.replace("'", "''") + "'"
    return value


def _blockquote(text: str) -> str:
    """Prefix every line of *text* with '> ' for a valid Markdown blockquote."""
    return "\n".join(f"> {line}" for line in text.splitlines())


def _inline_safe(text: str) -> str:
    """Replace newlines in inline text so they don't break Markdown structure."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def export_session_markdown(
    session: dict[str, Any],
    turns: list[dict[str, Any]],
    *,
    project_name: str | None = None,
) -> str:
    """Render a session and its turns as a Markdown document.

    The output has a YAML frontmatter block followed by Markdown sections.
    It is intentionally plain and git-friendly (no HTML, no Rich markup).

    Args:
        session: Session dict as returned by ``get_session()`` / ``list_sessions()``.
        turns: List of turn dicts as returned by ``list_turns()``.
        project_name: Optional project name to embed in frontmatter.

    Returns:
        A UTF-8-safe Markdown string.
    """
    session_id: str = session.get("id", "unknown")
    session_type: str = session.get("session_type") or "unknown"
    started_at: str = session.get("started_at") or ""
    ended_at = session.get("ended_at")
    total_turns: int = session.get("total_turns") or len(turns)
    session_title: str | None = session.get("session_title")
    session_summary: str | None = session.get("session_summary")

    status = ended_at if ended_at else "active"

    # --- YAML frontmatter ---
    fm_lines: list[str] = [
        "---",
        f"id: {_yaml_scalar(session_id)}",
        f"type: {_yaml_scalar(session_type)}",
        f"started: {_yaml_scalar(started_at)}",
        f"ended: {_yaml_scalar(str(status))}",
        f"turns: {total_turns}",
    ]
    if project_name is not None:
        fm_lines.append(f"project: {_yaml_scalar(project_name)}")
    fm_lines.append(f"exported: {_iso_now()}")
    fm_lines.append("---")

    # --- Title ---
    display_title = session_title if session_title else session_id[:8]
    body_lines: list[str] = [
        "",
        f"# Session: {_inline_safe(display_title)}",
        "",
    ]

    # --- Summary block ---
    if session_summary:
        body_lines += [
            _blockquote(session_summary),
            "",
        ]

    # --- Metadata summary ---
    body_lines += [
        "## Metadata",
        "",
        f"- **ID:** `{session_id}`",
        f"- **Type:** {session_type}",
        f"- **Started:** {started_at}",
        f"- **Status:** {status}",
        "",
    ]

    # --- Turns ---
    if turns:
        body_lines += [
            "## Turns",
            "",
        ]
        for turn in turns:
            num = turn.get("turn_number", "?")
            user_msg = turn.get("user_message") or ""
            asst_summary = turn.get("assistant_summary") or ""
            git_hash = turn.get("git_commit_hash")

            body_lines.append(f"### Turn {num}")
            body_lines.append("")
            if user_msg:
                body_lines.append(f"**User:** {_inline_safe(user_msg)}")
                body_lines.append("")
            if asst_summary:
                body_lines.append(f"**Assistant:** {_inline_safe(asst_summary)}")
                body_lines.append("")
            if git_hash:
                body_lines.append(f"*Commit: `{git_hash}`*")
                body_lines.append("")
            body_lines.append("---")
            body_lines.append("")

    return "\n".join(fm_lines) + "\n" + "\n".join(body_lines)
