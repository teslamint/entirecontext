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
from datetime import datetime, timezone
from pathlib import Path


def _normalize_ts(ts: str) -> str:
    """Normalize ISO timestamps to a comparable format (+00:00 suffix)."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc).isoformat()


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
                entry = json.loads(line)
                entry["started_at"] = _normalize_ts(entry["started_at"])
                blocks.append(entry)
    return sorted(blocks, key=lambda b: b["started_at"])


def sessions_in_block(conn: sqlite3.Connection, start: str, end: str | None) -> list[dict]:
    """Get qualifying sessions (total_turns >= 5) within a time window.

    Uses total_turns only (no checkpoint requirement) to keep the gate
    treatment-independent — injection ON/OFF must not affect which sessions
    qualify, or the experiment introduces selection bias.
    """
    query = """
        SELECT s.id, s.total_turns, s.started_at, s.ended_at
        FROM sessions s
        WHERE s.total_turns >= 5
          AND s.started_at >= ?
    """
    params: list = [start]
    if end:
        query += " AND s.started_at < ?"
        params.append(end)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def manual_retrieval_count(
    conn: sqlite3.Connection, session_ids: list[str], start: str, end: str | None
) -> int:
    """Count manual retrieval events (non-proactive) in given sessions within a time window."""
    if not session_ids:
        return 0
    placeholders = ",".join("?" for _ in session_ids)
    query = f"""
        SELECT COUNT(*) FROM retrieval_events
        WHERE session_id IN ({placeholders})
          AND search_type NOT IN ('session_start', 'session_start_ranked', 'post_tool_use', 'user_prompt', 'lesson_surfacing')
          AND created_at >= ?
    """
    params: list = list(session_ids) + [start]
    if end:
        query += " AND created_at < ?"
        params.append(end)
    row = conn.execute(query, params).fetchone()
    return row[0]


def analyze(conn: sqlite3.Connection, blocks: list[dict]) -> dict:
    block_results = []
    for i, block in enumerate(blocks):
        end = blocks[i + 1]["started_at"] if i + 1 < len(blocks) else None
        sessions = sessions_in_block(conn, block["started_at"], end)
        session_ids = [s["id"] for s in sessions]
        manual_count = manual_retrieval_count(conn, session_ids, block["started_at"], end)

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

    pair_deltas = []
    for on_b, off_b in pairs:
        on_turns = on_b["avg_turns"]
        off_turns = off_b["avg_turns"]
        pair_deltas.append(
            {
                "pair": (on_b["block_id"], off_b["block_id"]),
                "on_sessions": on_b["qualifying_sessions"],
                "off_sessions": off_b["qualifying_sessions"],
                "avg_turns_delta": round(on_turns - off_turns, 3) if on_turns is not None and off_turns is not None else None,
                "manual_retrieval_delta": on_b["manual_retrieval_events"] - off_b["manual_retrieval_events"],
            }
        )

    return {
        "total_blocks": len(block_results),
        "block_details": block_results,
        "pairs": len(pairs),
        "pair_deltas": pair_deltas,
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
    if result["pair_deltas"]:
        print("\nPer-pair deltas (ON - OFF):")
        for pd in result["pair_deltas"]:
            print(f"  Pair {pd['pair']}: avg_turns_delta={pd['avg_turns_delta']}, manual_retrieval_delta={pd['manual_retrieval_delta']}")
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
