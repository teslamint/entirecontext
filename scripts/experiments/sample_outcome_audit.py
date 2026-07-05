#!/usr/bin/env python3
"""Sample N=50 auto-inferred 'accepted' outcomes for human audit.

Produces a label-blinded review sheet: the recorded outcome is NOT in the output,
so the reviewer judges from transcript alone before comparing.

Usage:
    python scripts/experiments/sample_outcome_audit.py [--db PATH] [--n 50] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_to_relative(path: str, repo_root: str) -> str:
    """Strip repo root prefix from an absolute path to get a relative path."""
    prefix = repo_root.rstrip(os.sep) + os.sep
    if path.startswith(prefix):
        return path[len(prefix):]
    return path


def _relevant_content_paths(
    session_turns: list, decision_files_set: set, conn: sqlite3.Connection, repo_root: str
) -> list[str]:
    """Select content_paths around the turns where decision files were touched."""
    overlap_turn_indices = []
    all_content: list[tuple[int, str]] = []

    for i, turn in enumerate(session_turns):
        tc = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn["id"],)).fetchone()
        if not tc:
            continue
        all_content.append((i, tc["content_path"]))

        if turn["files_touched"]:
            try:
                parsed = json.loads(turn["files_touched"])
                touched = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                touched = []
            touched_rel = {_normalize_to_relative(f, repo_root) for f in touched}
            if touched_rel & decision_files_set:
                overlap_turn_indices.append(i)

    if not overlap_turn_indices:
        return [cp for _, cp in all_content[:5]]

    center = overlap_turn_indices[0]
    window_start = max(0, center - 2)
    window_end = center + 3
    selected = [cp for idx, cp in all_content if window_start <= idx < window_end]
    return selected[:5]


def sample_accepted_outcomes(
    conn: sqlite3.Connection, n: int = 50, repo_root: str = "."
) -> list[dict]:
    """Sample N auto-inferred 'accepted' outcomes, label-blinded."""
    rows = conn.execute(
        """
        SELECT do.id as outcome_id, do.decision_id, do.session_id,
               do.note, do.created_at,
               d.title as decision_title
        FROM decision_outcomes do
        JOIN decisions d ON d.id = do.decision_id
        WHERE do.outcome_type = 'accepted'
          AND do.note LIKE 'auto: session_end%'
          AND do.session_id IS NOT NULL
        ORDER BY do.created_at DESC
        """
    ).fetchall()

    cases = [dict(r) for r in rows]
    if len(cases) > n:
        cases = random.sample(cases, n)

    repo_root_abs = os.path.abspath(repo_root)

    review_sheet = []
    for case in cases:
        sid = case["session_id"]
        did = case["decision_id"]

        decision_files = [
            r["file_path"]
            for r in conn.execute("SELECT file_path FROM decision_files WHERE decision_id = ?", (did,)).fetchall()
        ]
        decision_files_set = set(decision_files)

        session_turns = conn.execute(
            "SELECT id, turn_number, files_touched FROM turns WHERE session_id = ? ORDER BY turn_number",
            (sid,),
        ).fetchall()

        files_touched_all = set()
        for turn in session_turns:
            if turn["files_touched"]:
                try:
                    parsed = json.loads(turn["files_touched"])
                    if isinstance(parsed, list):
                        files_touched_all.update(
                            _normalize_to_relative(f, repo_root_abs) for f in parsed
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

        file_overlap = sorted(decision_files_set & files_touched_all)
        content_paths = _relevant_content_paths(session_turns, decision_files_set, conn, repo_root_abs)

        review_sheet.append(
            {
                "outcome_id": case["outcome_id"],
                "session_id": sid,
                "decision_id": did,
                "decision_title": case["decision_title"],
                "decision_files": decision_files,
                "file_overlap": file_overlap,
                "session_turn_count": len(session_turns),
                "content_paths": content_paths,
                # outcome_type intentionally withheld for blind review
            }
        )

    return review_sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample outcomes for audit")
    parser.add_argument("--db", default=".entirecontext/db/local.db")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--output", default="scripts/experiments/output/audit_cases.jsonl")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(args.db)
    cases = sample_accepted_outcomes(conn, n=args.n, repo_root=args.repo_root)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for case in cases:
            f.write(json.dumps(case) + "\n")

    print(f"Wrote {len(cases)} cases to {out_path}")


if __name__ == "__main__":
    main()
