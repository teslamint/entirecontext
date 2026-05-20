"""E5: End-to-end PDI test (PR-E E5).

Verifies: prompt → rank_decisions_for_prompt → optimize_for_context_budget
→ handler stdout JSON. One matching decision fixture.

Uses an in-memory DB with the full schema and one seeded decision.
"""

from __future__ import annotations

import json
from unittest.mock import patch


def _make_db_with_decision():
    from entirecontext.db.connection import get_memory_db
    from entirecontext.db.migration import bootstrap_schema

    conn = get_memory_db()
    bootstrap_schema(conn)

    conn.execute(
        """INSERT INTO decisions (
            id, title, rationale, scope, staleness_status,
            rejected_alternatives, supporting_evidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "aaaabbbb-cccc-dddd-eeee-ffffffffffff",
            "Use SQLite WAL mode for agent memory",
            "WAL mode allows concurrent readers without blocking writes, critical for hook throughput.",
            "db",
            "fresh",
            "[]",
            "[]",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO decision_files (decision_id, file_path, added_at) VALUES (?, ?, ?)",
        ("aaaabbbb-cccc-dddd-eeee-ffffffffffff", "src/entirecontext/db/connection.py", "2026-01-01T00:00:00Z"),
    )
    return conn


class TestE2EPDI:
    def test_prompt_to_stdout_json(self, capsys, tmp_path):
        conn = _make_db_with_decision()
        hook_data = {
            "hook_type": "UserPromptSubmit",
            "session_id": "sess-e2e-001",
            "cwd": str(tmp_path),
            "prompt": "should we use WAL mode for the SQLite database?",
        }
        config = {
            "decisions": {
                "injection": {
                    "inject_on_user_prompt": True,
                    "top_k": 5,
                    "max_tokens": 800,
                    "min_confidence": 0.0,
                    "inject_timeout_ms": 250,
                }
            }
        }

        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value=str(tmp_path)),
            patch("entirecontext.core.config.load_config", return_value=config),
            patch("entirecontext.db.get_db", return_value=conn),
            patch(
                "entirecontext.core.decision_prompt_surfacing._get_uncommitted_diff",
                return_value="diff --git a/src/entirecontext/db/connection.py",
            ),
            patch(
                "entirecontext.core.decision_prompt_surfacing._get_recent_commit_shas",
                return_value=[],
            ),
        ):
            from entirecontext.hooks.handler import _handle_user_prompt

            result = _handle_user_prompt(hook_data)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip(), "Expected JSON on stdout"

        payload = json.loads(captured.out.strip())
        assert "hookSpecificOutput" in payload
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert "SQLite WAL" in ctx, f"Expected decision title in context, got: {ctx[:200]}"
        assert "aaaabbbb" in ctx, f"Expected decision ID prefix in context, got: {ctx[:200]}"
        conn.close()

    def test_no_matching_decisions_no_stdout(self, capsys, tmp_path):
        conn = _make_db_with_decision()
        hook_data = {
            "hook_type": "UserPromptSubmit",
            "session_id": "sess-e2e-002",
            "cwd": str(tmp_path),
            "prompt": "unrelated topic about meteorology",
        }
        config = {
            "decisions": {
                "injection": {
                    "inject_on_user_prompt": True,
                    "top_k": 5,
                    "max_tokens": 800,
                    "min_confidence": 0.99,
                    "inject_timeout_ms": 250,
                }
            }
        }

        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value=str(tmp_path)),
            patch("entirecontext.core.config.load_config", return_value=config),
            patch("entirecontext.db.get_db", return_value=conn),
            patch("entirecontext.core.decision_prompt_surfacing._get_uncommitted_diff", return_value=None),
            patch("entirecontext.core.decision_prompt_surfacing._get_recent_commit_shas", return_value=[]),
        ):
            from entirecontext.hooks.handler import _handle_user_prompt

            result = _handle_user_prompt(hook_data)

        assert result == 0
        captured = capsys.readouterr()
        assert not captured.out.strip()
        conn.close()
