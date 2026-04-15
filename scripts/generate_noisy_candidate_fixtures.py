"""Tier 2 noisy candidate fixture generator (manual, one-shot).

Samples N real sessions from the dev .entirecontext/db/local.db, redacts every
text field via core.content_filter.redact_content, and writes static JSON
fixtures under tests/fixtures/noisy_candidates/real/.

This script is checked in for reproducibility. The test suite does NOT invoke
it at collection time — tier 2 fixture tests skip cleanly when the output
files are absent, so a fresh clone still passes the full suite.

Usage (from the repo root, inside `uv run`):

    uv run python scripts/generate_noisy_candidate_fixtures.py \
        --out tests/fixtures/noisy_candidates/real \
        --count 5

The generator intentionally avoids calling any LLM. Recording the model
response for each fixture is a follow-up step done by hand after review.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_ec_db_path(repo_root: Path) -> Path:
    path = repo_root / ".entirecontext" / "db" / "local.db"
    if not path.exists():
        raise FileNotFoundError(f"dev DB not found at {path}. Run ec commands in this repo first.")
    return path


def _sample_sessions(conn, count: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.id, s.session_title, s.session_summary, s.total_turns,
               (SELECT COUNT(*) FROM checkpoints WHERE session_id = s.id) AS checkpoint_count
        FROM sessions s
        WHERE s.total_turns >= 3
          AND s.ended_at IS NOT NULL
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (count,),
    ).fetchall()
    return [dict(r) for r in rows]


def _collect_session_payload(conn, session_id: str) -> dict:
    from entirecontext.core.content_filter import redact_content

    session_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session_row:
        return {}
    turns = conn.execute(
        "SELECT id, turn_number, user_message, assistant_summary, files_touched "
        "FROM turns WHERE session_id = ? ORDER BY turn_number ASC",
        (session_id,),
    ).fetchall()
    checkpoints = conn.execute(
        "SELECT id, created_at, diff_summary, files_snapshot "
        "FROM checkpoints WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,),
    ).fetchall()
    assessments = conn.execute(
        "SELECT a.id, a.checkpoint_id, a.verdict, a.impact_summary, "
        "       a.roadmap_alignment, a.tidy_suggestion, a.diff_summary "
        "FROM assessments a JOIN checkpoints c ON a.checkpoint_id = c.id "
        "WHERE c.session_id = ?",
        (session_id,),
    ).fetchall()

    def _redact(value):
        if value is None:
            return None
        return redact_content(str(value))

    return {
        "session": {
            "id": session_row["id"],
            "session_title": _redact(session_row["session_title"]),
            "session_summary": _redact(session_row["session_summary"]),
        },
        "turns": [
            {
                "id": t["id"],
                "turn_number": t["turn_number"],
                "user_message": _redact(t["user_message"]),
                "assistant_summary": _redact(t["assistant_summary"]),
                "files_touched": t["files_touched"],
            }
            for t in turns
        ],
        "checkpoints": [
            {
                "id": c["id"],
                "created_at": c["created_at"],
                "diff_summary": _redact(c["diff_summary"]),
                "files_snapshot": c["files_snapshot"],
            }
            for c in checkpoints
        ],
        "assessments": [
            {
                "id": a["id"],
                "checkpoint_id": a["checkpoint_id"],
                "verdict": a["verdict"],
                "impact_summary": _redact(a["impact_summary"]),
                "roadmap_alignment": _redact(a["roadmap_alignment"]),
                "tidy_suggestion": _redact(a["tidy_suggestion"]),
                "diff_summary": _redact(a["diff_summary"]),
            }
            for a in assessments
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--out", required=True, help="Output directory for fixtures")
    parser.add_argument("--count", type=int, default=5, help="Number of sessions to sample")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fail fast if the dev DB is missing; the script is intentionally
    # a manual one-shot and should not invent an empty DB.
    _ensure_ec_db_path(repo_root)

    # Import after path adjustments
    sys.path.insert(0, str(repo_root / "src"))
    from entirecontext.db import get_db

    conn = get_db(str(repo_root))
    try:
        sessions = _sample_sessions(conn, args.count)
        if not sessions:
            print("No eligible sessions found (need ≥3 turns, ended).", file=sys.stderr)
            return 1
        for idx, meta in enumerate(sessions, start=1):
            payload = _collect_session_payload(conn, meta["id"])
            if not payload:
                continue
            out_file = out_dir / f"real_{idx:02d}_{meta['id'][:8]}.json"
            out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"wrote {out_file}")
    finally:
        conn.close()

    print(f"generated {len(sessions)} fixtures under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
