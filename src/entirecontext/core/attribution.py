"""File attribution — human vs agent line-level tracking."""

from __future__ import annotations

import sqlite3
from typing import Any


def get_file_attributions(
    conn: sqlite3.Connection,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> list[dict]:
    """Get per-line attributions for a file.

    Returns list of attribution dicts with line ranges and types.
    """
    query = "SELECT a.*, ag.name as agent_name, ag.agent_type FROM attributions a LEFT JOIN agents ag ON a.agent_id = ag.id WHERE a.file_path = ?"
    params: list[Any] = [file_path]

    if start_line is not None:
        query += " AND a.end_line >= ?"
        params.append(start_line)
    if end_line is not None:
        query += " AND a.start_line <= ?"
        params.append(end_line)

    query += " ORDER BY a.start_line"
    rows = conn.execute(query, params).fetchall()

    return [
        {
            "id": r["id"],
            "file_path": r["file_path"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "attribution_type": r["attribution_type"],
            "agent_name": r["agent_name"] or r["agent_type"] if r["agent_id"] else None,
            "agent_id": r["agent_id"],
            "session_id": r["session_id"],
            "turn_id": r["turn_id"],
            "confidence": r["confidence"],
        }
        for r in rows
    ]


def get_file_attribution_summary(conn: sqlite3.Connection, file_path: str) -> dict:
    """Get aggregated attribution stats for a file.

    Returns dict with total lines, human/agent percentages, and per-agent breakdown.
    """
    rows = conn.execute(
        "SELECT a.attribution_type, a.start_line, a.end_line, a.agent_id, "
        "ag.name as agent_name, ag.agent_type "
        "FROM attributions a LEFT JOIN agents ag ON a.agent_id = ag.id "
        "WHERE a.file_path = ? ORDER BY a.start_line",
        (file_path,),
    ).fetchall()

    if not rows:
        return {
            "file_path": file_path,
            "total_lines": 0,
            "human_lines": 0,
            "agent_lines": 0,
            "human_pct": 0.0,
            "agent_pct": 0.0,
            "agents": {},
        }

    human_lines = 0
    agent_lines = 0
    agents: dict[str, int] = {}

    for r in rows:
        line_count = r["end_line"] - r["start_line"] + 1
        if r["attribution_type"] == "human":
            human_lines += line_count
        else:
            agent_lines += line_count
            agent_name = r["agent_name"] or r["agent_type"] or r["agent_id"] or "unknown"
            agents[agent_name] = agents.get(agent_name, 0) + line_count

    total = human_lines + agent_lines
    return {
        "file_path": file_path,
        "total_lines": total,
        "human_lines": human_lines,
        "agent_lines": agent_lines,
        "human_pct": round(human_lines / total * 100, 1) if total > 0 else 0.0,
        "agent_pct": round(agent_lines / total * 100, 1) if total > 0 else 0.0,
        "agents": agents,
    }
