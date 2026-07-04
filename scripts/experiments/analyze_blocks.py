#!/usr/bin/env python3
"""Analyze injection ON/OFF block experiment results.

Reads experiment-blocks.jsonl and joins with sessions DB to compute
paired block differences for quality proxies.

Block log format (one entry per block transition):
    {"block_id": 1, "injection": true, "started_at": "2026-07-10T00:00:00Z", "qualifying_sessions": 0}

Usage:
    python scripts/experiments/analyze_blocks.py [--db PATH] [--blocks PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_blocks(blocks_path: str) -> list[dict]:
    path = Path(blocks_path)
    if not path.exists():
        print(f"Blocks file not found: {path}", file=sys.stderr)
        sys.exit(1)

    blocks = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                blocks.append(json.loads(line))
    return sorted(blocks, key=lambda b: b["started_at"])


def sessions_in_block(conn: sqlite3.Connection, start: str, end: str | None) -> list[dict]:
    """Get qualifying sessions (total_turns >= 5 AND has checkpoint) within a time window."""
    query = """
        SELECT s.id, s.total_turns, s.started_at, s.ended_at,
               (SELECT COUNT(*) FROM checkpoints c WHERE c.session_id = s.id) as checkpoint_count
        FROM sessions s
        WHERE s.total_turns >= 5
          AND s.started_at >= ?
    """
    params: list = [start]
    if end:
        query += " AND s.started_at < ?"
        params.append(end)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows if r["checkpoint_count"] > 0]


def manual_retrieval_count(conn: sqlite3.Connection, session_ids: list[str]) -> int:
    """Count manual retrieval events (non-proactive) in given sessions."""
    if not session_ids:
        return 0
    placeholders = ",".join("?" for _ in session_ids)
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM retrieval_events
        WHERE session_id IN ({placeholders})
          AND search_type NOT IN ('session_start', 'post_tool_use', 'user_prompt')
        """,
        session_ids,
    ).fetchone()
    return row[0]


def analyze(conn: sqlite3.Connection, blocks: list[dict]) -> dict:
    block_results = []
    for i, block in enumerate(blocks):
        end = blocks[i + 1]["started_at"] if i + 1 < len(blocks) else None
        sessions = sessions_in_block(conn, block["started_at"], end)
        session_ids = [s["id"] for s in sessions]
        manual_count = manual_retrieval_count(conn, session_ids)

        block_results.append(
            {
                "block_id": block["block_id"],
                "injection": block["injection"],
                "started_at": block["started_at"],
                "ended_at": end,
                "qualifying_sessions": len(sessions),
                "avg_turns": (sum(s["total_turns"] for s in sessions) / len(sessions) if sessions else None),
                "manual_retrieval_events": manual_count,
            }
        )

    on_blocks = [b for b in block_results if b["injection"]]
    off_blocks = [b for b in block_results if not b["injection"]]
    pairs = list(zip(on_blocks, off_blocks))

    return {
        "total_blocks": len(block_results),
        "block_details": block_results,
        "pairs": len(pairs),
        "compensation_check": {
            "on_manual_retrieval_avg": (
                sum(b["manual_retrieval_events"] for b in on_blocks) / len(on_blocks) if on_blocks else None
            ),
            "off_manual_retrieval_avg": (
                sum(b["manual_retrieval_events"] for b in off_blocks) / len(off_blocks) if off_blocks else None
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze block experiment")
    parser.add_argument("--db", default=".entirecontext/db/local.db")
    parser.add_argument(
        "--blocks",
        default="scripts/experiments/output/experiment-blocks.jsonl",
    )
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(args.db)
    blocks = load_blocks(args.blocks)
    result = analyze(conn, blocks)
    print(json.dumps(result, indent=2))

    print("\n--- Summary ---")
    print(f"Blocks: {result['total_blocks']}, Pairs: {result['pairs']}")
    if result["pairs"] < 4:
        print("WARNING: <4 block pairs. Directional signal only; do not claim significance.")
    comp = result["compensation_check"]
    if comp["on_manual_retrieval_avg"] is not None and comp["off_manual_retrieval_avg"] is not None:
        if comp["off_manual_retrieval_avg"] > comp["on_manual_retrieval_avg"] * 1.5:
            print(
                "WARNING: OFF blocks show elevated manual retrieval — "
                "estimand shifts from 'injection vs nothing' to 'proactive vs on-demand'."
            )


if __name__ == "__main__":
    main()
