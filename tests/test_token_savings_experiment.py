"""Tests for the token-savings experiment: shared estimator, injection
telemetry, and the scripts/experiments/token_savings.py analyzer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from entirecontext.core.telemetry import record_injection_event
from entirecontext.core.tokens import estimate_tokens

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "experiments" / "token_savings.py"


def _load_analyzer():
    spec = importlib.util.spec_from_file_location("token_savings", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


token_savings = _load_analyzer()


# ---------------------------------------------------------------------------
# seeding helpers
# ---------------------------------------------------------------------------


def _project_id(conn) -> str:
    return conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]


def _seed_session(conn, *, started_at: str, turn_sizes: list[int], turns_without_content: int = 0) -> str:
    """Insert a session with one turn per entry in turn_sizes (bytes of
    transcript content), plus optional consolidated turns lacking content."""
    session_id = str(uuid4())
    total = len(turn_sizes) + turns_without_content
    conn.execute(
        """
        INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, total_turns)
        VALUES (?, ?, 'interactive', ?, ?, ?)
        """,
        (session_id, _project_id(conn), started_at, started_at, total),
    )
    for i in range(total):
        turn_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO turns (id, session_id, turn_number, content_hash, timestamp)
            VALUES (?, ?, ?, 'h', ?)
            """,
            (turn_id, session_id, i + 1, started_at),
        )
        if i < len(turn_sizes):
            conn.execute(
                "INSERT INTO turn_content (turn_id, content_path, content_size, content_hash) VALUES (?, ?, ?, 'h')",
                (turn_id, f"content/{session_id}/{turn_id}.jsonl", turn_sizes[i]),
            )
    conn.commit()
    return session_id


# ---------------------------------------------------------------------------
# core.tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_fallback_when_encoding_none(self):
        text = "fallback text"
        assert estimate_tokens(text, encoding=None) == max(1, len(text.encode("utf-8")) // 3)

    def test_custom_encoding_used(self):
        class FakeEncoding:
            def encode(self, text, **kwargs):
                return [1, 2, 3]

        assert estimate_tokens("anything", encoding=FakeEncoding()) == 3

    def test_default_returns_positive_int(self):
        result = estimate_tokens("some ordinary text")
        assert isinstance(result, int)
        assert result > 0

    def test_special_tokens_do_not_raise(self):
        assert estimate_tokens("with <|endoftext|> inside") > 0


# ---------------------------------------------------------------------------
# core.telemetry.record_injection_event
# ---------------------------------------------------------------------------


class TestRecordInjectionEvent:
    def test_writes_operation_event_with_token_metadata(self, ec_db):
        event = record_injection_event(
            ec_db,
            channel="user_prompt",
            payload="## Related Decisions\n\nsome payload",
            item_count=2,
        )
        ec_db.commit()
        row = ec_db.execute("SELECT * FROM operation_events WHERE id = ?", (event["id"],)).fetchone()
        assert row["operation_name"] == "context_injection"
        assert row["phase"] == "user_prompt"
        assert row["status"] == "ok"
        meta = json.loads(row["metadata"])
        assert meta["injected_tokens"] > 0
        assert meta["injected_chars"] == len("## Related Decisions\n\nsome payload")
        assert meta["item_count"] == 2

    def test_invalid_channel_rejected(self, ec_db):
        with pytest.raises(ValueError):
            record_injection_event(ec_db, channel="nonsense", payload="x", item_count=1)


# ---------------------------------------------------------------------------
# analyzer
# ---------------------------------------------------------------------------


class TestSessionTokenStats:
    def test_cumulative_and_final_tokens(self, ec_db):
        sid = _seed_session(ec_db, started_at="2026-01-01T00:00:00+00:00", turn_sizes=[4000, 8000, 12000])
        stats = token_savings.session_token_stats(ec_db, sid, bytes_per_token=4.0)
        assert stats["turns"] == 3
        assert stats["turns_with_content"] == 3
        assert stats["cumulative_transcript_tokens"] == (4000 + 8000 + 12000) // 4
        assert stats["final_context_tokens"] == 12000 // 4

    def test_consolidated_turns_reduce_coverage(self, ec_db):
        sid = _seed_session(ec_db, started_at="2026-01-01T00:00:00+00:00", turn_sizes=[4000], turns_without_content=2)
        stats = token_savings.session_token_stats(ec_db, sid)
        assert stats["turns"] == 3
        assert stats["turns_with_content"] == 1


class TestSessionInjectionStats:
    def test_sums_by_channel(self, ec_db):
        sid = _seed_session(ec_db, started_at="2026-01-01T00:00:00+00:00", turn_sizes=[1000] * 5)
        record_injection_event(ec_db, channel="user_prompt", payload="a" * 400, item_count=1, session_id=sid)
        record_injection_event(
            ec_db, channel="session_start_decisions", payload="b" * 200, item_count=2, session_id=sid
        )
        ec_db.commit()
        stats = token_savings.session_injection_stats(ec_db, sid)
        assert stats["injection_events"] == 2
        assert stats["injected_tokens"] > 0
        assert set(stats["by_channel"]) == {"user_prompt", "session_start_decisions"}
        assert stats["injected_tokens"] == sum(stats["by_channel"].values())


class TestAnalyzeTokenBlocks:
    def test_paired_on_off_delta(self, ec_db):
        blocks = [
            {"block_id": 1, "injection": True, "started_at": "2026-01-01T00:00:00+00:00"},
            {"block_id": 2, "injection": False, "started_at": "2026-01-02T00:00:00+00:00"},
        ]
        # ON block: cheaper sessions (5 turns x 4000 bytes -> 5000 tokens).
        on_sid = _seed_session(ec_db, started_at="2026-01-01T06:00:00+00:00", turn_sizes=[4000] * 5)
        record_injection_event(ec_db, channel="user_prompt", payload="c" * 400, item_count=1, session_id=on_sid)
        ec_db.commit()
        # OFF block: costlier sessions (5 turns x 8000 bytes -> 10000 tokens).
        _seed_session(ec_db, started_at="2026-01-02T06:00:00+00:00", turn_sizes=[8000] * 5)

        result = token_savings.analyze_token_blocks(ec_db, blocks, bytes_per_token=4.0)
        assert result["total_blocks"] == 2
        assert result["pairs"] == 1
        delta = result["pair_deltas"][0]
        assert delta["pair"] == (1, 2)
        assert delta["net_saved_tokens_per_session"] == 5000.0
        assert delta["avg_injected_tokens_on"] > 0
        assert delta["savings_roi"] == pytest.approx(5000.0 / delta["avg_injected_tokens_on"], rel=0.02)
        assert any("<4 block pairs" in w for w in result["warnings"])

    def test_short_sessions_do_not_qualify(self, ec_db):
        blocks = [{"block_id": 1, "injection": True, "started_at": "2026-01-01T00:00:00+00:00"}]
        _seed_session(ec_db, started_at="2026-01-01T06:00:00+00:00", turn_sizes=[4000] * 2)
        result = token_savings.analyze_token_blocks(ec_db, blocks)
        assert result["block_details"][0]["sessions"] == 0


class TestSummarizeAll:
    def test_baseline_summary(self, ec_db):
        _seed_session(ec_db, started_at="2026-01-01T00:00:00+00:00", turn_sizes=[4000] * 5)
        _seed_session(ec_db, started_at="2026-01-01T01:00:00+00:00", turn_sizes=[4000] * 2)  # below gate
        result = token_savings.summarize_all(ec_db, bytes_per_token=4.0)
        assert result["sessions"] == 1
        assert result["avg_session_tokens"] == 5000.0
        assert result["content_coverage"] == 1.0
        assert len(result["top_sessions_by_tokens"]) == 1
