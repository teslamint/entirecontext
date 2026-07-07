#!/usr/bin/env python3
"""Flip the experiment block when qualifying-session count reaches N.

Qualifying session: total_turns >= 5 (treatment-independent gate).
Reads the last block entry from experiment-blocks.jsonl, counts qualifying
sessions since that block started, and if count >= N, appends a new block
with the opposite injection setting and updates .entirecontext/config.toml.

Usage:
    python scripts/experiments/flip_block.py [--n 5] [--db PATH] [--blocks PATH] [--config PATH]
    python scripts/experiments/flip_block.py --init  # Create first block entry (ON)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_ts(ts: str) -> str:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc).isoformat()


def load_last_block(blocks_path: Path) -> dict | None:
    if not blocks_path.exists():
        return None
    last = None
    with blocks_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                last = json.loads(line)
    return last


def count_qualifying_since(conn: sqlite3.Connection, since: str) -> int:
    """Count sessions with total_turns >= 5 started after `since`."""
    rows = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE total_turns >= 5 AND started_at >= ?",
        (since,),
    ).fetchone()
    return rows[0]


def update_config_toml(config_path: Path, block_value: str) -> None:
    """Set experiment_block in the config TOML file."""
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            f"[decisions.injection]\nexperiment_block = \"{block_value}\"\n"
        )
        return

    content = config_path.read_text()

    if "experiment_block" in content:
        content = re.sub(
            r'experiment_block\s*=\s*"[^"]*"',
            f'experiment_block = "{block_value}"',
            content,
        )
    elif "[decisions.injection]" in content:
        content = content.replace(
            "[decisions.injection]",
            f'[decisions.injection]\nexperiment_block = "{block_value}"',
        )
    else:
        content += f'\n[decisions.injection]\nexperiment_block = "{block_value}"\n'

    config_path.write_text(content)


def init_block(blocks_path: Path) -> dict:
    """Create the first block entry."""
    entry = {
        "block_id": 1,
        "injection": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "qualifying_sessions": 0,
    }
    blocks_path.parent.mkdir(parents=True, exist_ok=True)
    with blocks_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def flip(
    conn: sqlite3.Connection,
    blocks_path: Path,
    config_path: Path,
    n: int,
) -> dict | None:
    """Check if a flip is due and execute it. Returns new block entry or None."""
    last = load_last_block(blocks_path)
    if last is None:
        print("No blocks file. Use --init to create the first block.", file=sys.stderr)
        return None

    since = _normalize_ts(last["started_at"])
    qualifying = count_qualifying_since(conn, since)

    print(f"Current block: {last['block_id']} (injection={'ON' if last['injection'] else 'OFF'})")
    print(f"Qualifying sessions since block start: {qualifying}/{n}")

    if qualifying < n:
        print(f"Not yet — need {n - qualifying} more qualifying sessions to flip.")
        return None

    new_injection = not last["injection"]
    new_block = {
        "block_id": last["block_id"] + 1,
        "injection": new_injection,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "qualifying_sessions": 0,
    }

    with blocks_path.open("a") as f:
        f.write(json.dumps(new_block) + "\n")

    block_value = "on" if new_injection else "off"
    update_config_toml(config_path, block_value)

    print(f"FLIPPED to block {new_block['block_id']} (injection={'ON' if new_injection else 'OFF'})")
    print(f"Config updated: experiment_block = \"{block_value}\"")
    return new_block


def main() -> None:
    parser = argparse.ArgumentParser(description="Flip experiment block")
    parser.add_argument("--n", type=int, default=5, help="Qualifying sessions per block")
    parser.add_argument("--db", default=".entirecontext/db/local.db")
    parser.add_argument("--blocks", default="scripts/experiments/output/experiment-blocks.jsonl")
    parser.add_argument("--config", default=".entirecontext/config.toml")
    parser.add_argument("--init", action="store_true", help="Initialize first block (ON)")
    args = parser.parse_args()

    blocks_path = Path(args.blocks)
    config_path = Path(args.config)

    if args.init:
        if blocks_path.exists() and blocks_path.read_text().strip():
            print("Blocks file already exists. Delete it first to re-initialize.", file=sys.stderr)
            sys.exit(1)
        entry = init_block(blocks_path)
        update_config_toml(config_path, "on")
        print(f"Initialized block 1 (injection=ON) at {entry['started_at']}")
        print("Config updated: experiment_block = \"on\"")
        return

    if not Path(args.db).exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(args.db)
    flip(conn, blocks_path, config_path, n=args.n)


if __name__ == "__main__":
    main()
