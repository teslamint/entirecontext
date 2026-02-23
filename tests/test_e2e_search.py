"""E2E tests for search after data capture."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.search import fts_search, regex_search
from entirecontext.core.session import update_session
from entirecontext.db import get_db
from entirecontext.hooks.session_lifecycle import on_session_end, on_session_start
from entirecontext.hooks.turn_capture import on_stop, on_tool_use, on_user_prompt

runner = CliRunner()


@pytest.fixture
def seeded_repo(ec_repo, transcript_file):
    """EC repo with one session, two turns, seeded via hook flow."""
    cwd = str(ec_repo)
    sid = "search-session"

    on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})

    on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Fix auth bug"})
    on_tool_use(
        {
            "session_id": sid,
            "cwd": cwd,
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/auth.py"},
        }
    )
    t1 = transcript_file(
        [
            {"role": "user", "content": "Fix auth bug"},
            {"role": "assistant", "content": "Fixed authentication issue in auth.py"},
        ],
        name="srch_t1.jsonl",
    )
    on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t1})

    on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Add tests for auth"})
    t2 = transcript_file(
        [
            {"role": "user", "content": "Add tests for auth"},
            {"role": "assistant", "content": "Added comprehensive tests"},
        ],
        name="srch_t2.jsonl",
    )
    on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t2})

    on_session_end({"session_id": sid, "cwd": cwd})
    return ec_repo


class TestRegexSearch:
    def test_finds_by_user_message(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = regex_search(conn, "auth")
        conn.close()
        assert len(results) >= 1
        assert any("auth" in (r.get("user_message") or "").lower() for r in results)

    def test_file_filter(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = regex_search(conn, "auth", file_filter="src/auth.py")
        conn.close()
        assert len(results) >= 1

    def test_no_results(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = regex_search(conn, "nonexistent_xyz_pattern")
        conn.close()
        assert len(results) == 0

    def test_session_target_with_summary(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        update_session(conn, "search-session", session_summary="Auth bug fix session")
        results = regex_search(conn, "Auth", target="session")
        conn.close()
        assert len(results) >= 1


class TestFTSSearch:
    def test_finds_by_user_message(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = fts_search(conn, "auth")
        conn.close()
        assert len(results) >= 1

    def test_file_filter(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = fts_search(conn, "auth", file_filter="src/auth.py")
        conn.close()
        assert len(results) >= 1

    def test_no_results(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = fts_search(conn, "nonexistent_xyz_pattern")
        conn.close()
        assert len(results) == 0


class TestContentSearch:
    def test_searches_content_files(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = regex_search(conn, "authentication", target="content")
        conn.close()
        assert len(results) >= 1

    def test_content_no_results(self, seeded_repo):
        conn = get_db(str(seeded_repo))
        results = regex_search(conn, "nonexistent_xyz", target="content")
        conn.close()
        assert len(results) == 0


class TestSearchCLI:
    def test_regex_cli(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        result = runner.invoke(app, ["search", "auth"])
        assert result.exit_code == 0
        assert "auth" in result.output.lower()

    def test_fts_cli(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        result = runner.invoke(app, ["search", "auth", "--fts"])
        assert result.exit_code == 0
        assert "auth" in result.output.lower()

    def test_no_results_cli(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        result = runner.invoke(app, ["search", "nonexistent_xyz"])
        assert result.exit_code == 0
        assert "no results" in result.output.lower()


class TestSemanticSearch:
    @pytest.fixture
    def seeded_with_embeddings(self, seeded_repo):
        """Seeded repo with fake embeddings for semantic search."""
        import struct

        conn = get_db(str(seeded_repo))
        turns = conn.execute("SELECT id FROM turns ORDER BY turn_number").fetchall()
        fake_vec = struct.pack("3f", 1.0, 1.0, 1.0)
        for turn in turns:
            conn.execute(
                "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
                "VALUES (?, 'turn', ?, 'all-MiniLM-L6-v2', ?, 3, 'hash')",
                (f"emb-{turn['id']}", turn["id"], fake_vec),
            )
        conn.commit()
        conn.close()
        return seeded_repo

    def test_semantic_search_returns_results(self, seeded_with_embeddings):
        import struct
        from unittest.mock import patch

        fake_vec = struct.pack("3f", 1.0, 1.0, 1.0)
        conn = get_db(str(seeded_with_embeddings))
        with patch("entirecontext.core.embedding.embed_text", return_value=fake_vec):
            from entirecontext.core.embedding import semantic_search

            results = semantic_search(conn, "auth bug")
        conn.close()
        assert len(results) >= 1
        assert all(r.get("score", 0) > 0 for r in results)

    def test_semantic_search_with_file_filter(self, seeded_with_embeddings):
        import struct
        from unittest.mock import patch

        fake_vec = struct.pack("3f", 1.0, 1.0, 1.0)
        conn = get_db(str(seeded_with_embeddings))
        with patch("entirecontext.core.embedding.embed_text", return_value=fake_vec):
            from entirecontext.core.embedding import semantic_search

            results = semantic_search(conn, "auth", file_filter="src/auth.py")
        conn.close()
        assert len(results) >= 1
        for r in results:
            if r.get("source_type") == "turn":
                assert "src/auth.py" in (r.get("files_touched") or "")

    def test_semantic_search_with_since_filter(self, seeded_with_embeddings):
        import struct
        from unittest.mock import patch

        fake_vec = struct.pack("3f", 1.0, 1.0, 1.0)
        conn = get_db(str(seeded_with_embeddings))
        with patch("entirecontext.core.embedding.embed_text", return_value=fake_vec):
            from entirecontext.core.embedding import semantic_search

            results = semantic_search(conn, "auth", since="2099-01-01")
        conn.close()
        assert len(results) == 0

    def test_semantic_search_import_error(self, seeded_with_embeddings):
        from unittest.mock import patch

        conn = get_db(str(seeded_with_embeddings))
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            from entirecontext.core.embedding import semantic_search

            with pytest.raises(ImportError, match="sentence-transformers"):
                semantic_search(conn, "auth")
        conn.close()


class TestSearchWithQueryRedaction:
    @pytest.fixture
    def seeded_with_secret(self, ec_repo, transcript_file):
        cwd = str(ec_repo)
        sid = "redact-session"
        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "fix password=secret123 in config"})
        t1 = transcript_file(
            [
                {"role": "user", "content": "fix password=secret123"},
                {"role": "assistant", "content": "Fixed token=abc123 in the config"},
            ],
            name="redact_t1.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t1})
        on_session_end({"session_id": sid, "cwd": cwd})
        return ec_repo

    def test_search_results_redacted(self, seeded_with_secret):
        config = {
            "filtering": {
                "query_redaction": {
                    "enabled": True,
                    "patterns": [r"password\s*=\s*\S+", r"token\s*=\s*\S+"],
                    "replacement": "[FILTERED]",
                }
            }
        }
        conn = get_db(str(seeded_with_secret))
        results = regex_search(conn, "config", config=config)
        conn.close()
        assert len(results) >= 1
        for r in results:
            assert "secret123" not in (r.get("user_message") or "")
            assert "abc123" not in (r.get("assistant_summary") or "")

    def test_search_unredacted_when_disabled(self, seeded_with_secret):
        config = {
            "filtering": {
                "query_redaction": {
                    "enabled": False,
                    "patterns": [r"password\s*=\s*\S+"],
                }
            }
        }
        conn = get_db(str(seeded_with_secret))
        results = regex_search(conn, "config", config=config)
        conn.close()
        assert len(results) >= 1
