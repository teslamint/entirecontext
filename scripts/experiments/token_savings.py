#!/usr/bin/env python3
"""Estimate LLM token savings from EntireContext context injection.

Two data sources, both captured by normal dogfooding:

1. Injection overhead — ``operation_events`` rows with
   ``operation_name = 'context_injection'`` record the token size of every
   proactively injected payload (SessionStart decisions/lessons, PDI,
   PostToolUse). Written by ``core.telemetry.record_injection_event``.
2. Session transcript footprint — each captured turn stores the full
   Claude Code transcript JSONL at that point (``turn_content.content_size``
   bytes). Because every turn re-sends the whole transcript to the model,
   the sum of per-turn transcript sizes approximates the cumulative input
   payload the LLM processed over the session.

Joined with the ON/OFF block log from ``flip_block.py``, paired blocks give
a net token delta per session:

    net_saved_per_session = OFF avg session tokens - ON avg session tokens

which already accounts for the injected overhead (injected text lands in
the transcript of ON sessions). The overhead is also reported separately
so the ROI of injection is visible.

Usage:
    python scripts/experiments/token_savings.py --summary        # whole-DB baseline
    python scripts/experiments/token_savings.py                  # per-block A/B analysis
    python scripts/experiments/token_savings.py --json           # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_blocks import (  # noqa: E402
    _connect,
    load_blocks,
    manual_retrieval_count,
    sessions_in_block,
)

DEFAULT_BYTES_PER_TOKEN = 4.0
INJECTION_OPERATION_NAME = "context_injection"


def session_token_stats(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN,
) -> dict:
    """Transcript-derived token stats for one session.

    ``cumulative_transcript_tokens`` sums every turn's full-transcript size
    (proxy for total input tokens across the session); ``final_context_tokens``
    is the largest single transcript (proxy for the final context size).
    Consolidated turns have no ``turn_content`` row — coverage is reported so
    low-coverage sessions can be discounted.
    """
    rows = conn.execute(
        """
        SELECT tc.content_size
        FROM turn_content tc
        JOIN turns t ON t.id = tc.turn_id
        WHERE t.session_id = ?
        """,
        (session_id,),
    ).fetchall()
    sizes = [r[0] or 0 for r in rows]
    total_turns = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)).fetchone()[0]
    return {
        "turns": total_turns,
        "turns_with_content": len(sizes),
        "cumulative_transcript_tokens": int(sum(sizes) / bytes_per_token),
        "final_context_tokens": int(max(sizes) / bytes_per_token) if sizes else 0,
    }


def session_injection_stats(conn: sqlite3.Connection, session_id: str) -> dict:
    """Injected-payload token totals for one session, split by channel."""
    rows = conn.execute(
        "SELECT phase, metadata FROM operation_events WHERE operation_name = ? AND session_id = ?",
        (INJECTION_OPERATION_NAME, session_id),
    ).fetchall()
    total = 0
    by_channel: dict[str, int] = {}
    events = 0
    for row in rows:
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except (ValueError, TypeError):
            continue
        tokens = int(meta.get("injected_tokens") or 0)
        total += tokens
        by_channel[row["phase"]] = by_channel.get(row["phase"], 0) + tokens
        events += 1
    return {"injected_tokens": total, "injection_events": events, "by_channel": by_channel}


def _aggregate_sessions(
    conn: sqlite3.Connection,
    sessions: list[dict],
    *,
    bytes_per_token: float,
) -> dict:
    """Aggregate token stats over a list of session rows."""
    per_session = []
    for s in sessions:
        tok = session_token_stats(conn, s["id"], bytes_per_token=bytes_per_token)
        inj = session_injection_stats(conn, s["id"])
        per_session.append({"id": s["id"], **tok, **inj})

    n = len(per_session)
    covered = [p for p in per_session if p["turns_with_content"] > 0]

    def _avg(key: str, pool: list[dict]) -> float | None:
        return round(sum(p[key] for p in pool) / len(pool), 1) if pool else None

    total_turns = sum(p["turns"] for p in covered)
    total_tokens = sum(p["cumulative_transcript_tokens"] for p in covered)
    return {
        "sessions": n,
        "sessions_with_content": len(covered),
        "content_coverage": (
            round(sum(p["turns_with_content"] for p in per_session) / sum(p["turns"] for p in per_session), 3)
            if sum(p["turns"] for p in per_session)
            else None
        ),
        "avg_session_tokens": _avg("cumulative_transcript_tokens", covered),
        "avg_tokens_per_turn": round(total_tokens / total_turns, 1) if total_turns else None,
        "avg_final_context_tokens": _avg("final_context_tokens", covered),
        "avg_injected_tokens": _avg("injected_tokens", per_session),
        "total_injected_tokens": sum(p["injected_tokens"] for p in per_session),
        "per_session": per_session,
    }


def analyze_token_blocks(
    conn: sqlite3.Connection,
    blocks: list[dict],
    *,
    bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN,
) -> dict:
    """Per-block token aggregates plus paired ON-OFF deltas."""
    block_results = []
    for i, block in enumerate(blocks):
        end = blocks[i + 1]["started_at"] if i + 1 < len(blocks) else None
        sessions = sessions_in_block(conn, block["started_at"], end)
        agg = _aggregate_sessions(conn, sessions, bytes_per_token=bytes_per_token)
        agg.pop("per_session")
        manual = manual_retrieval_count(conn, [s["id"] for s in sessions], block["started_at"], end)
        block_results.append(
            {
                "block_id": block["block_id"],
                "injection": block["injection"],
                "started_at": block["started_at"],
                "ended_at": end,
                "manual_retrieval_events": manual,
                **agg,
            }
        )

    on_blocks = [b for b in block_results if b["injection"]]
    off_blocks = [b for b in block_results if not b["injection"]]
    pairs = list(zip(on_blocks, off_blocks))

    pair_deltas = []
    for on_b, off_b in pairs:
        on_tok = on_b["avg_session_tokens"]
        off_tok = off_b["avg_session_tokens"]
        net_saved = round(off_tok - on_tok, 1) if on_tok is not None and off_tok is not None else None
        injected = on_b["avg_injected_tokens"] or 0
        pair_deltas.append(
            {
                "pair": (on_b["block_id"], off_b["block_id"]),
                "on_sessions": on_b["sessions"],
                "off_sessions": off_b["sessions"],
                "net_saved_tokens_per_session": net_saved,
                "tokens_per_turn_delta": (
                    round(on_b["avg_tokens_per_turn"] - off_b["avg_tokens_per_turn"], 1)
                    if on_b["avg_tokens_per_turn"] is not None and off_b["avg_tokens_per_turn"] is not None
                    else None
                ),
                "avg_injected_tokens_on": injected,
                "savings_roi": (round(net_saved / injected, 2) if net_saved is not None and injected > 0 else None),
            }
        )

    warnings = []
    if len(pairs) < 4:
        warnings.append("<4 block pairs. Directional signal only; do not claim significance.")
    low_coverage = [b["block_id"] for b in block_results if (b["content_coverage"] or 0) < 0.8 and b["sessions"] > 0]
    if low_coverage:
        warnings.append(
            f"Blocks {low_coverage} have <80% turn-content coverage (consolidation deleted transcripts); "
            "token totals there are underestimates."
        )

    return {
        "bytes_per_token": bytes_per_token,
        "total_blocks": len(block_results),
        "block_details": block_results,
        "pairs": len(pairs),
        "pair_deltas": pair_deltas,
        "warnings": warnings,
    }


def summarize_all(conn: sqlite3.Connection, *, bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN) -> dict:
    """Whole-DB baseline: token footprint and injection overhead, no blocks."""
    sessions = [dict(r) for r in conn.execute("SELECT id, total_turns FROM sessions WHERE total_turns >= 5").fetchall()]
    agg = _aggregate_sessions(conn, sessions, bytes_per_token=bytes_per_token)
    per_session = agg.pop("per_session")
    top = sorted(per_session, key=lambda p: p["cumulative_transcript_tokens"], reverse=True)[:5]
    return {
        "bytes_per_token": bytes_per_token,
        "gate": "total_turns >= 5",
        **agg,
        "top_sessions_by_tokens": [
            {k: p[k] for k in ("id", "turns", "cumulative_transcript_tokens", "injected_tokens")} for p in top
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate token savings from context injection")
    parser.add_argument("--db", default=".entirecontext/db/local.db")
    parser.add_argument("--blocks", default="scripts/experiments/output/experiment-blocks.jsonl")
    parser.add_argument("--bytes-per-token", type=float, default=DEFAULT_BYTES_PER_TOKEN)
    parser.add_argument("--summary", action="store_true", help="Whole-DB baseline instead of block analysis")
    parser.add_argument("--json", action="store_true", help="JSON output only")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(args.db)

    if args.summary:
        result = summarize_all(conn, bytes_per_token=args.bytes_per_token)
        print(json.dumps(result, indent=2))
        if not args.json:
            print("\n--- Summary ---")
            print(f"Qualifying sessions: {result['sessions']} (content coverage: {result['content_coverage']})")
            print(f"Avg session tokens: {result['avg_session_tokens']}, avg/turn: {result['avg_tokens_per_turn']}")
            print(
                f"Injected overhead: total {result['total_injected_tokens']} tokens, "
                f"avg {result['avg_injected_tokens']}/session"
            )
        return

    result = analyze_token_blocks(conn, load_blocks(args.blocks), bytes_per_token=args.bytes_per_token)
    print(json.dumps(result, indent=2))
    if not args.json:
        print("\n--- Summary ---")
        print(f"Blocks: {result['total_blocks']}, Pairs: {result['pairs']}")
        for pd in result["pair_deltas"]:
            print(
                f"  Pair {pd['pair']}: net_saved/session={pd['net_saved_tokens_per_session']}, "
                f"injected(ON)={pd['avg_injected_tokens_on']}, ROI={pd['savings_roi']}"
            )
        for w in result["warnings"]:
            print(f"WARNING: {w}")


if __name__ == "__main__":
    main()
