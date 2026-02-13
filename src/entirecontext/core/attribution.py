"""File attribution — human vs agent line-level tracking."""

from __future__ import annotations

import re
import sqlite3
import subprocess
from typing import Any
from uuid import uuid4


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


def create_attribution(
    conn: sqlite3.Connection,
    checkpoint_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
    attribution_type: str,
    agent_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    confidence: float = 1.0,
) -> dict:
    """Create a single attribution record."""
    attr_id = str(uuid4())
    conn.execute(
        "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, "
        "attribution_type, agent_id, session_id, turn_id, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            attr_id,
            checkpoint_id,
            file_path,
            start_line,
            end_line,
            attribution_type,
            agent_id,
            session_id,
            turn_id,
            confidence,
        ),
    )
    conn.commit()
    return {
        "id": attr_id,
        "checkpoint_id": checkpoint_id,
        "file_path": file_path,
        "start_line": start_line,
        "end_line": end_line,
        "attribution_type": attribution_type,
        "agent_id": agent_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "confidence": confidence,
    }


def _parse_diff_hunks(diff_output: str) -> list[dict]:
    """Parse unified diff output into file/hunk records.

    Returns list of {file_path, start_line, end_line} for each hunk in the new file.
    """
    hunks = []
    current_file = None
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for line in diff_output.splitlines():
        if line.startswith("diff --git"):
            current_file = None
        elif line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+++ /dev/null"):
            current_file = None
        elif current_file and line.startswith("@@"):
            m = hunk_re.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                if count > 0:
                    hunks.append(
                        {
                            "file_path": current_file,
                            "start_line": start,
                            "end_line": start + count - 1,
                        }
                    )

    return hunks


def generate_attributions_from_diff(
    conn: sqlite3.Connection,
    checkpoint_id: str,
    session_id: str,
    agent_id: str | None,
    turn_id: str | None,
    repo_path: str,
    commit_hash: str,
) -> int:
    """Parse git diff for a commit and generate attribution records for each hunk."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}~1..{commit_hash}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0

    diff_output = result.stdout
    if not diff_output.strip():
        return 0

    hunks = _parse_diff_hunks(diff_output)
    attribution_type = "agent" if agent_id else "human"

    count = 0
    for hunk in hunks:
        create_attribution(
            conn,
            checkpoint_id=checkpoint_id,
            file_path=hunk["file_path"],
            start_line=hunk["start_line"],
            end_line=hunk["end_line"],
            attribution_type=attribution_type,
            agent_id=agent_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        count += 1

    return count


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
