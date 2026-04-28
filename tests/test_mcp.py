"""Tests for MCP server tool functions (unit tests with mock DB)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema
from entirecontext.mcp import runtime


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, session_title, session_summary, total_turns) "
        "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01', 'Test Session', 'A test session', 3)"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES ('t1', 's1', 1, 'fix auth bug', 'Fixed authentication', 'hash1', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES ('t2', 's1', 2, 'add tests', 'Added unit tests', 'hash2', '2025-01-02')"
    )
    conn.commit()
    yield conn
    conn.close()


class TestMCPDetectCurrentSession:
    def test_detect_current_session(self, db):
        from entirecontext.mcp.server import _detect_current_session

        session_id = _detect_current_session(db)
        assert session_id == "s1"

    def test_detect_no_session(self):
        conn = get_memory_db()
        init_schema(conn)
        from entirecontext.mcp.server import _detect_current_session

        session_id = _detect_current_session(conn)
        assert session_id is None
        conn.close()


class TestMCPToolsDirectCalls:
    """Test the underlying logic that MCP tools use, without requiring mcp package."""

    def test_search_regex(self, db):
        from entirecontext.core.search import regex_search

        results = regex_search(db, "auth", target="turn")
        assert len(results) >= 1
        assert any("auth" in r.get("user_message", "").lower() for r in results)

    def test_search_fts(self, db):
        from entirecontext.core.search import fts_search

        results = fts_search(db, "authentication", target="turn")
        assert len(results) >= 1

    def test_session_context(self, db):
        session = db.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone()
        assert session is not None
        assert session["session_title"] == "Test Session"

        turns = db.execute("SELECT * FROM turns WHERE session_id = 's1' ORDER BY turn_number DESC LIMIT 10").fetchall()
        assert len(turns) == 2

    def test_checkpoint_list_empty(self, db):
        checkpoints = db.execute("SELECT * FROM checkpoints").fetchall()
        assert len(checkpoints) == 0

    def test_attribution_query(self, db):
        db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc')")
        db.execute("INSERT INTO agents (id, agent_type, name) VALUES ('a1', 'claude', 'Claude')")
        db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id) "
            "VALUES ('attr1', 'cp1', 'src/main.py', 1, 10, 'agent', 'a1')"
        )
        db.commit()

        rows = db.execute(
            "SELECT a.*, ag.name as agent_name FROM attributions a LEFT JOIN agents ag ON a.agent_id = ag.id WHERE a.file_path = ?",
            ("src/main.py",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["agent_name"] == "Claude"

    def test_related_by_files(self, db):
        db.execute(
            "UPDATE turns SET files_touched = ? WHERE id = 't1'",
            (json.dumps(["src/auth.py"]),),
        )
        db.commit()

        rows = db.execute(
            "SELECT * FROM turns WHERE files_touched LIKE ?",
            ("%auth.py%",),
        ).fetchall()
        assert len(rows) == 1


class TestMCPToolIntegration:
    """Integration tests calling MCP tool functions directly via asyncio.run()."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        class _NoCloseConn:
            """Proxy that prevents tool finally-blocks from closing the shared fixture connection."""

            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def close(self):
                pass

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

        wrapper = _NoCloseConn(db)
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
        return wrapper

    def test_search_regex_hit(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("auth")))
        assert result["count"] >= 1
        assert any("auth" in r["summary"].lower() for r in result["results"])
        assert result["retrieval_event_id"]

    def test_search_regex_miss(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("nonexistent_xyz_999")))
        assert result["count"] == 0
        assert result["retrieval_event_id"]

    def test_search_fts_hit(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("authentication", search_type="fts")))
        assert result["count"] >= 1

    def test_checkpoint_list_empty(self, mock_repo_db):
        from entirecontext.mcp.server import ec_checkpoint_list

        result = json.loads(asyncio.run(ec_checkpoint_list()))
        assert result["count"] == 0
        assert result["checkpoints"] == []

    def test_checkpoint_list_with_data(self, mock_repo_db):
        from entirecontext.mcp.server import ec_checkpoint_list

        mock_repo_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at, diff_summary) "
            "VALUES ('cp1', 's1', 'abc123', 'main', '2025-01-01', 'Added auth')"
        )
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_checkpoint_list()))
        assert result["count"] == 1
        assert result["checkpoints"][0]["commit_hash"] == "abc123"

    def test_checkpoint_list_records_selection(self, mock_repo_db):
        from entirecontext.core.telemetry import record_retrieval_event
        from entirecontext.mcp.server import ec_checkpoint_list

        mock_repo_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at, diff_summary) "
            "VALUES ('cp-select', 's1', 'abc123', 'main', '2025-01-01', 'Added auth')"
        )
        mock_repo_db.commit()
        event = record_retrieval_event(
            mock_repo_db,
            source="mcp",
            search_type="regex",
            target="turn",
            query="auth",
            result_count=1,
            latency_ms=5,
            session_id="s1",
            turn_id="t1",
        )
        result = json.loads(asyncio.run(ec_checkpoint_list(retrieval_event_id=event["id"])))
        assert result["selection_id"] is not None
        assert result["selection_ids"]

    def test_session_context_auto_detect(self, mock_repo_db):
        from entirecontext.mcp.server import ec_session_context

        result = json.loads(asyncio.run(ec_session_context()))
        assert result["session_id"] == "s1"
        assert result["session_title"] == "Test Session"
        assert len(result["recent_turns"]) == 2

    def test_session_context_explicit_id(self, mock_repo_db):
        from entirecontext.mcp.server import ec_session_context

        result = json.loads(asyncio.run(ec_session_context(session_id="s1")))
        assert result["session_id"] == "s1"
        assert result["total_turns"] == 3

    def test_session_context_records_selection(self, mock_repo_db):
        from entirecontext.core.telemetry import record_retrieval_event
        from entirecontext.mcp.server import ec_session_context

        event = record_retrieval_event(
            mock_repo_db,
            source="mcp",
            search_type="regex",
            target="turn",
            query="session",
            result_count=1,
            latency_ms=5,
            session_id="s1",
            turn_id="t1",
        )
        result = json.loads(asyncio.run(ec_session_context(session_id="s1", retrieval_event_id=event["id"])))
        assert result["selection_id"] is not None

    def test_session_context_not_found(self, mock_repo_db):
        from entirecontext.mcp.server import ec_session_context

        result = json.loads(asyncio.run(ec_session_context(session_id="nonexistent")))
        assert "error" in result

    def test_attribution_with_data(self, mock_repo_db):
        from entirecontext.mcp.server import ec_attribution

        mock_repo_db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc')")
        mock_repo_db.execute("INSERT INTO agents (id, agent_type, name) VALUES ('a1', 'claude', 'Claude')")
        mock_repo_db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id, session_id) "
            "VALUES ('attr1', 'cp1', 'src/main.py', 1, 10, 'agent', 'a1', 's1')"
        )
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_attribution("src/main.py")))
        assert result["file_path"] == "src/main.py"
        assert len(result["attributions"]) == 1
        assert result["attributions"][0]["agent_name"] == "Claude"

    def test_attribution_empty(self, mock_repo_db):
        from entirecontext.mcp.server import ec_attribution

        result = json.loads(asyncio.run(ec_attribution("nonexistent.py")))
        assert result["file_path"] == "nonexistent.py"
        assert len(result["attributions"]) == 0

    def test_rewind_valid_checkpoint(self, mock_repo_db):
        from entirecontext.mcp.server import ec_rewind

        mock_repo_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, diff_summary) "
            "VALUES ('cp1', 's1', 'abc123', 'main', 'Added auth')"
        )
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_rewind("cp1")))
        assert result["checkpoint_id"] == "cp1"
        assert result["commit_hash"] == "abc123"
        assert result["session"]["title"] == "Test Session"

    def test_rewind_not_found(self, mock_repo_db):
        from entirecontext.mcp.server import ec_rewind

        result = json.loads(asyncio.run(ec_rewind("nonexistent")))
        assert "error" in result

    def test_related_by_query(self, mock_repo_db):
        from entirecontext.mcp.server import ec_related

        result = json.loads(asyncio.run(ec_related(query="auth")))
        assert result["count"] >= 1
        assert any("auth" in r["summary"].lower() for r in result["related"])

    def test_related_by_files(self, mock_repo_db):
        from entirecontext.mcp.server import ec_related

        mock_repo_db.execute("UPDATE turns SET files_touched = ? WHERE id = 't1'", (json.dumps(["src/auth.py"]),))
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_related(files=["src/auth.py"])))
        assert result["count"] >= 1
        assert any(r["relevance"] == "file:src/auth.py" for r in result["related"])

    def test_turn_content_valid(self, mock_repo_db):
        from entirecontext.mcp.server import ec_turn_content

        result = json.loads(asyncio.run(ec_turn_content("t1")))
        assert result["turn_id"] == "t1"
        assert result["user_message"] == "fix auth bug"
        assert result["content"] is None
        assert result["content_path"] is None

    def test_turn_content_not_found(self, mock_repo_db):
        from entirecontext.mcp.server import ec_turn_content

        result = json.loads(asyncio.run(ec_turn_content("nonexistent")))
        assert "error" in result

    def test_ec_search_semantic(self, mock_repo_db):
        import struct
        from unittest.mock import patch

        from entirecontext.mcp.server import ec_search

        fake_vec = struct.pack("3f", 1.0, 1.0, 1.0)
        mock_repo_db.execute(
            "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
            "VALUES ('emb1', 'turn', 't1', 'all-MiniLM-L6-v2', ?, 3, 'hash')",
            (fake_vec,),
        )
        mock_repo_db.commit()

        with patch("entirecontext.core.embedding.embed_text", return_value=fake_vec):
            result = json.loads(asyncio.run(ec_search("auth", search_type="semantic")))
        assert result["count"] >= 1

    def test_ec_search_semantic_import_error(self, mock_repo_db):
        from unittest.mock import patch

        from entirecontext.mcp.server import ec_search

        with patch(
            "entirecontext.core.embedding.semantic_search",
            side_effect=ImportError("sentence-transformers is required"),
        ):
            result = json.loads(asyncio.run(ec_search("auth", search_type="semantic")))
        assert "error" in result
        assert "sentence-transformers" in result["error"]

    def test_no_repo_returns_error(self, monkeypatch):
        from entirecontext.mcp.server import ec_search
        from entirecontext.mcp.runtime import RepoResolutionError

        monkeypatch.setattr(
            "entirecontext.mcp.runtime.get_repo_db",
            lambda repo_hint=None: (_ for _ in ()).throw(
                RepoResolutionError("No repo found. Run 'ec init' in your repo or set ENTIRECONTEXT_REPO_PATH.")
            ),
        )
        result = json.loads(asyncio.run(ec_search("test")))
        assert "error" in result
        assert "set ENTIRECONTEXT_REPO_PATH" in result["error"]


class FakeRepoContext:
    def __init__(self, conn, repo_path: str, *, initialized: bool = True):
        self.conn = conn
        self.repo_path = repo_path
        self.project = {"id": "p1", "name": Path(repo_path).name, "repo_path": repo_path} if initialized else None
        self.current_session_id = "s1"

    def close(self):
        return None


class FakeGlobalContext:
    def __init__(self, repos: list[dict]):
        self._repos = repos

    def list_registered_repos(self, names=None):
        if names is None:
            return list(self._repos)
        return [repo for repo in self._repos if repo["repo_name"] in names]

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class TestMCPRepoResolver:
    def test_resolver_explicit_repo_hint(self, db, monkeypatch):
        from entirecontext.core.context import RepoContext
        from entirecontext.mcp import runtime

        hint_path = "/tmp/hint-repo"
        monkeypatch.setenv("ENTIRECONTEXT_REPO_PATH", "/tmp/env-repo-should-be-ignored")
        context = FakeRepoContext(db, hint_path)
        cwd_calls = []

        def from_cwd(cls, cwd=".", require_project=False):
            cwd_calls.append(cwd)
            return context

        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(from_cwd))

        conn, repo_path = runtime.get_repo_db(repo_hint=hint_path)
        assert conn is db
        assert repo_path == hint_path
        assert cwd_calls == [hint_path]

    def test_resolver_repo_hint_nonexistent(self, monkeypatch):
        from entirecontext.core.context import RepoContext
        from entirecontext.mcp import runtime

        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(lambda cls, cwd=".", require_project=False: None))

        with pytest.raises(runtime.RepoResolutionError, match="does not exist or is not a git repo"):
            runtime.get_repo_db(repo_hint="/tmp/nonexistent")

    def test_resolver_repo_hint_uninitialized(self, db, monkeypatch):
        from entirecontext.core.context import RepoContext
        from entirecontext.mcp import runtime

        hint_path = "/tmp/uninit-repo"

        def from_cwd(cls, cwd=".", require_project=False):
            return FakeRepoContext(db, hint_path, initialized=False)

        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(from_cwd))

        with pytest.raises(runtime.RepoResolutionError, match="not initialized"):
            runtime.get_repo_db(repo_hint=hint_path)

    def test_resolver_cwd_match(self, db, monkeypatch):
        from entirecontext.core.context import RepoContext
        from entirecontext.mcp import runtime

        monkeypatch.delenv("ENTIRECONTEXT_REPO_PATH", raising=False)
        context = FakeRepoContext(db, "/tmp/test")
        cwd_calls = []

        def from_cwd(cls, cwd=".", require_project=False):
            cwd_calls.append(cwd)
            return context

        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(from_cwd))

        conn, repo_path = runtime.get_repo_db()
        assert conn is db
        assert repo_path == "/tmp/test"
        assert cwd_calls == ["."]

    def test_resolver_cwd_mismatch_with_env_override(self, db, monkeypatch):
        from entirecontext.core.context import RepoContext
        from entirecontext.mcp import runtime

        env_repo = "/tmp/env-repo"
        monkeypatch.setenv("ENTIRECONTEXT_REPO_PATH", env_repo)

        def from_cwd(cls, cwd=".", require_project=False):
            if cwd == env_repo:
                return FakeRepoContext(db, env_repo)
            return None

        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(from_cwd))

        conn, repo_path = runtime.get_repo_db()
        assert conn is db
        assert repo_path == env_repo

    def test_resolver_cwd_mismatch_single_registered_repo(self, db, monkeypatch, tmp_path):
        from entirecontext.core.context import GlobalContext, RepoContext
        from entirecontext.mcp import runtime

        repo_path = tmp_path / "only-repo"
        repo_path.mkdir()
        monkeypatch.delenv("ENTIRECONTEXT_REPO_PATH", raising=False)
        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(lambda cls, cwd=".", require_project=False: None))
        monkeypatch.setattr(
            GlobalContext,
            "create",
            classmethod(lambda cls: FakeGlobalContext([{"repo_name": "only-repo", "repo_path": str(repo_path)}])),
        )
        monkeypatch.setattr(
            RepoContext,
            "from_repo_path",
            classmethod(
                lambda cls, repo_path_arg, require_project=False: (
                    FakeRepoContext(db, str(repo_path)) if str(repo_path_arg) == str(repo_path) else None
                )
            ),
        )

        conn, resolved_repo_path = runtime.get_repo_db()
        assert conn is db
        assert resolved_repo_path == str(repo_path)

    def test_resolver_cwd_mismatch_multiple_registered_repos(self, monkeypatch, tmp_path):
        from entirecontext.core.context import GlobalContext, RepoContext
        from entirecontext.mcp import runtime

        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        monkeypatch.delenv("ENTIRECONTEXT_REPO_PATH", raising=False)
        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(lambda cls, cwd=".", require_project=False: None))
        monkeypatch.setattr(
            GlobalContext,
            "create",
            classmethod(
                lambda cls: FakeGlobalContext(
                    [
                        {"repo_name": "repo-a", "repo_path": str(repo_a)},
                        {"repo_name": "repo-b", "repo_path": str(repo_b)},
                    ]
                )
            ),
        )
        fake_dbs = []

        def make_fake_context(cls, repo_path_arg, require_project=False):
            db = get_memory_db()
            fake_dbs.append(db)
            return FakeRepoContext(db, str(repo_path_arg))

        monkeypatch.setattr(RepoContext, "from_repo_path", classmethod(make_fake_context))

        try:
            with pytest.raises(runtime.RepoResolutionError, match="Set ENTIRECONTEXT_REPO_PATH"):
                runtime.get_repo_db()
        finally:
            for db in fake_dbs:
                db.close()

    def test_resolver_ignores_deleted_repo_entries(self, db, monkeypatch, tmp_path):
        from entirecontext.core.context import GlobalContext, RepoContext
        from entirecontext.mcp import runtime

        valid_repo = tmp_path / "valid-repo"
        deleted_repo = tmp_path / "deleted-repo"
        valid_repo.mkdir()
        monkeypatch.delenv("ENTIRECONTEXT_REPO_PATH", raising=False)
        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(lambda cls, cwd=".", require_project=False: None))
        monkeypatch.setattr(
            GlobalContext,
            "create",
            classmethod(
                lambda cls: FakeGlobalContext(
                    [
                        {"repo_name": "deleted-repo", "repo_path": str(deleted_repo)},
                        {"repo_name": "valid-repo", "repo_path": str(valid_repo)},
                    ]
                )
            ),
        )
        monkeypatch.setattr(
            RepoContext,
            "from_repo_path",
            classmethod(
                lambda cls, repo_path_arg, require_project=False: (
                    FakeRepoContext(db, str(valid_repo)) if str(repo_path_arg) == str(valid_repo) else None
                )
            ),
        )

        conn, resolved_repo_path = runtime.get_repo_db()
        assert conn is db
        assert resolved_repo_path == str(valid_repo)

    def test_ec_search_uses_runtime_resolver(self, monkeypatch):
        from entirecontext.core.context import RepoContext
        from entirecontext.mcp.server import ec_search

        db = get_memory_db()
        init_schema(db)
        db.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/env-repo')")
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, session_title, session_summary, total_turns) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01', 'Test Session', 'A test session', 1)"
        )
        db.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
            "VALUES ('t1', 's1', 1, 'fix auth bug', 'Fixed authentication', 'hash1', '2025-01-01')"
        )
        db.commit()

        env_repo = "/tmp/env-repo"
        monkeypatch.setenv("ENTIRECONTEXT_REPO_PATH", env_repo)

        def from_cwd(cls, cwd=".", require_project=False):
            if cwd == env_repo:
                return FakeRepoContext(db, env_repo)
            return None

        monkeypatch.setattr(RepoContext, "from_cwd", classmethod(from_cwd))

        try:
            result = json.loads(asyncio.run(ec_search("auth")))
            assert result["count"] >= 1
            assert any("auth" in item["summary"].lower() for item in result["results"])
        finally:
            db.close()

    def test_resolve_repo_success(self, db, monkeypatch):
        from entirecontext.mcp import runtime

        monkeypatch.setattr(runtime, "get_repo_db", lambda repo_hint=None: (db, "/tmp/test"))

        (conn, path), error = runtime.resolve_repo()
        assert conn is db
        assert path == "/tmp/test"
        assert error is None

    def test_resolve_repo_failure(self, monkeypatch):
        from entirecontext.mcp import runtime

        monkeypatch.setattr(
            runtime,
            "get_repo_db",
            lambda repo_hint=None: (_ for _ in ()).throw(runtime.RepoResolutionError("No repo found.")),
        )

        (conn, path), error = runtime.resolve_repo()
        assert conn is None
        assert path is None
        assert error is not None
        parsed = json.loads(error)
        assert "error" in parsed
        assert "No repo found." in parsed["error"]


class TestMCPAssessAndFeedback:
    """Tests for ec_assess_create and ec_feedback MCP tools."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        class _NoCloseConn:
            """Proxy that prevents tool finally-blocks from closing the shared fixture connection."""

            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def close(self):
                pass

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

        wrapper = _NoCloseConn(db)
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
        return wrapper

    def test_ec_assess_create_direct(self, mock_repo_db):
        from entirecontext.mcp.server import ec_assess_create

        result = json.loads(
            asyncio.run(
                ec_assess_create(
                    verdict="expand",
                    impact_summary="Adds modular API surface",
                    roadmap_alignment="Aligned with Q1",
                    tidy_suggestion="Extract interface",
                    diff_summary="+ added new module",
                )
            )
        )
        assert result["verdict"] == "expand"
        assert result["impact_summary"] == "Adds modular API surface"
        assert result["model_name"] == "mcp-agent"
        assert result["id"]

    def test_ec_assess_create_llm(self, mock_repo_db, monkeypatch):
        from unittest.mock import MagicMock

        from entirecontext.mcp.server import ec_assess_create

        fake_backend = MagicMock()
        fake_backend.complete.return_value = json.dumps(
            {
                "verdict": "narrow",
                "impact_summary": "Tight coupling introduced",
                "roadmap_alignment": "Misaligned",
                "tidy_suggestion": "Decouple modules",
            }
        )
        monkeypatch.setattr("entirecontext.core.llm.get_backend", lambda *a, **kw: fake_backend)

        result = json.loads(
            asyncio.run(
                ec_assess_create(
                    diff="+ tightly coupled code",
                    backend="openai",
                    model="gpt-4o-mini",
                )
            )
        )
        assert result["verdict"] == "narrow"
        assert result["impact_summary"] == "Tight coupling introduced"
        assert result["model_name"] == "gpt-4o-mini"
        fake_backend.complete.assert_called_once()

    def test_ec_assess_create_no_diff_error(self, mock_repo_db):
        from entirecontext.mcp.server import ec_assess_create

        result = json.loads(asyncio.run(ec_assess_create()))
        assert "error" in result
        assert "diff" in result["error"].lower()

    def test_ec_feedback_agree(self, mock_repo_db):
        from entirecontext.core.futures import create_assessment
        from entirecontext.mcp.server import ec_feedback

        assessment = create_assessment(mock_repo_db, verdict="expand", impact_summary="Test")
        result = json.loads(asyncio.run(ec_feedback(assessment["id"], "agree", reason="Looks good")))
        assert result["status"] == "ok"
        assert result["feedback"] == "agree"
        assert result["assessment_id"] == assessment["id"]

    def test_ec_feedback_invalid(self, mock_repo_db):
        from entirecontext.core.futures import create_assessment
        from entirecontext.mcp.server import ec_feedback

        assessment = create_assessment(mock_repo_db, verdict="neutral", impact_summary="Test")
        result = json.loads(asyncio.run(ec_feedback(assessment["id"], "maybe")))
        assert "error" in result
        assert "Invalid feedback" in result["error"]

    def test_ec_feedback_auto_distill(self, mock_repo_db, monkeypatch, tmp_path):
        from entirecontext.core.futures import create_assessment
        from entirecontext.mcp.server import ec_feedback

        monkeypatch.setattr(
            "entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (mock_repo_db, str(tmp_path))
        )

        distill_calls = []

        def mock_auto_distill(repo_path):
            distill_calls.append(str(repo_path))
            return True

        monkeypatch.setattr("entirecontext.core.futures.auto_distill_lessons", mock_auto_distill)

        assessment = create_assessment(mock_repo_db, verdict="expand", impact_summary="Auto distill MCP test")
        result = json.loads(asyncio.run(ec_feedback(assessment["id"], "agree")))
        assert result["status"] == "ok"
        assert result["auto_distilled"] is True
        assert len(distill_calls) == 1
        assert distill_calls[0] == str(tmp_path)

    def test_ec_assess_create_invalid_verdict(self, mock_repo_db):
        from entirecontext.mcp.server import ec_assess_create

        result = json.loads(asyncio.run(ec_assess_create(verdict="invalid_verdict", impact_summary="Test")))
        assert "error" in result
        assert "Invalid verdict" in result["error"]

    def test_ec_assess_create_with_checkpoint_id(self, mock_repo_db):
        from entirecontext.mcp.server import ec_assess_create

        mock_repo_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at, diff_summary) "
            "VALUES ('cp-assess1', 's1', 'def456', 'main', '2025-01-01', 'Refactored auth module')"
        )
        mock_repo_db.commit()
        result = json.loads(
            asyncio.run(
                ec_assess_create(
                    verdict="expand",
                    impact_summary="Auth refactor",
                    checkpoint_id="cp-assess1",
                )
            )
        )
        assert result["verdict"] == "expand"
        assert result["checkpoint_id"] == "cp-assess1"
        assert result["diff_summary"] == "Refactored auth module"

    def test_ec_assess_create_reads_roadmap(self, mock_repo_db, monkeypatch, tmp_path):
        from unittest.mock import MagicMock

        from entirecontext.mcp.server import ec_assess_create

        roadmap_file = tmp_path / "ROADMAP.md"
        roadmap_file.write_text("# Roadmap\n- Phase 1: Auth\n- Phase 2: API", encoding="utf-8")
        monkeypatch.setattr(
            "entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (mock_repo_db, str(tmp_path))
        )

        fake_backend = MagicMock()
        fake_backend.complete.return_value = json.dumps(
            {
                "verdict": "expand",
                "impact_summary": "Aligned with roadmap",
                "roadmap_alignment": "Phase 1",
                "tidy_suggestion": "Continue",
            }
        )
        monkeypatch.setattr("entirecontext.core.llm.get_backend", lambda *a, **kw: fake_backend)

        result = json.loads(
            asyncio.run(
                ec_assess_create(
                    diff="+ new auth code",
                    backend="openai",
                    model="gpt-4o-mini",
                )
            )
        )
        assert result["verdict"] == "expand"
        call_args = fake_backend.complete.call_args
        user_prompt = call_args[0][1]
        assert "# Roadmap" in user_prompt
        assert "Phase 1: Auth" in user_prompt

    def test_ec_feedback_nonexistent_assessment(self, mock_repo_db):
        from entirecontext.mcp.server import ec_feedback

        result = json.loads(asyncio.run(ec_feedback("nonexistent-id-12345", "agree")))
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_ec_assess_create_llm_bad_json(self, mock_repo_db, monkeypatch):
        from unittest.mock import MagicMock

        from entirecontext.mcp.server import ec_assess_create

        fake_backend = MagicMock()
        fake_backend.complete.return_value = "not valid json {{"
        monkeypatch.setattr("entirecontext.core.llm.get_backend", lambda *a, **kw: fake_backend)

        result = json.loads(asyncio.run(ec_assess_create(diff="+ some code", backend="openai", model="gpt-4o-mini")))
        assert "error" in result
        assert "LLM analysis failed" in result["error"]


class TestMCPHybridSearch:
    """Tests for ec_search with search_type='hybrid'."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        class _NoCloseConn:
            """Proxy that prevents tool finally-blocks from closing the shared fixture connection."""

            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def close(self):
                pass

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

        wrapper = _NoCloseConn(db)
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
        return wrapper

    def test_search_hybrid_hit(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("auth", search_type="hybrid")))
        assert result["count"] >= 1
        assert any("auth" in r["summary"].lower() for r in result["results"])
        assert "hybrid_score" in result["results"][0]

    def test_search_hybrid_miss(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("nonexistent_xyz_999", search_type="hybrid")))
        assert result["count"] == 0


class TestMCPAstSearch:
    """Tests for ec_ast_search MCP tool."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (db, "/tmp/test"))
        db.execute(
            "INSERT INTO ast_symbols (id, file_path, symbol_type, name, qualified_name, start_line, end_line, docstring) "
            "VALUES ('sym1', 'src/auth.py', 'function', 'authenticate', 'auth.authenticate', 1, 10, 'Authenticate user')"
        )
        db.execute(
            "INSERT INTO ast_symbols (id, file_path, symbol_type, name, qualified_name, start_line, end_line, docstring) "
            "VALUES ('sym2', 'src/auth.py', 'class', 'AuthManager', 'auth.AuthManager', 12, 50, 'Auth manager class')"
        )
        db.execute(
            "INSERT INTO ast_symbols (id, file_path, symbol_type, name, qualified_name, start_line, end_line, docstring) "
            "VALUES ('sym3', 'src/utils.py', 'function', 'hash_password', 'utils.hash_password', 1, 5, 'Hash a password')"
        )
        db.commit()
        return db

    def test_ast_search_hit(self, mock_repo_db):
        from entirecontext.mcp.server import ec_ast_search

        result = json.loads(asyncio.run(ec_ast_search("authenticate")))
        assert result["count"] >= 1
        assert any(r["name"] == "authenticate" for r in result["results"])

    def test_ast_search_by_type(self, mock_repo_db):
        from entirecontext.mcp.server import ec_ast_search

        result = json.loads(asyncio.run(ec_ast_search("auth", symbol_type="class")))
        assert result["count"] >= 1
        assert all(r["symbol_type"] == "class" for r in result["results"])

    def test_ast_search_by_file(self, mock_repo_db):
        from entirecontext.mcp.server import ec_ast_search

        result = json.loads(asyncio.run(ec_ast_search("password", file_filter="src/utils.py")))
        assert result["count"] >= 1
        assert all(r["file_path"] == "src/utils.py" for r in result["results"])

    def test_ast_search_miss(self, mock_repo_db):
        from entirecontext.mcp.server import ec_ast_search

        result = json.loads(asyncio.run(ec_ast_search("nonexistent_xyz_999")))
        assert result["count"] == 0

    def test_ast_search_no_repo(self, monkeypatch):
        pytest.importorskip("mcp")
        from entirecontext.mcp.server import ec_ast_search

        monkeypatch.setattr(
            "entirecontext.mcp.runtime.get_repo_db",
            lambda repo_hint=None: (_ for _ in ()).throw(
                runtime.RepoResolutionError("No repo found. Run 'ec init' in your repo or set ENTIRECONTEXT_REPO_PATH.")
            ),
        )
        result = json.loads(asyncio.run(ec_ast_search("test")))
        assert "error" in result


class TestMCPGraph:
    """Tests for ec_graph MCP tool."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (db, "/tmp/test"))
        db.execute(
            "UPDATE turns SET files_touched = ?, git_commit_hash = ? WHERE id = 't1'",
            (json.dumps(["src/auth.py"]), "abc123"),
        )
        db.execute(
            "UPDATE turns SET files_touched = ?, git_commit_hash = ? WHERE id = 't2'",
            (json.dumps(["src/auth.py", "src/test.py"]), "def456"),
        )
        db.commit()
        return db

    def test_graph_basic(self, mock_repo_db):
        from entirecontext.mcp.server import ec_graph

        result = json.loads(asyncio.run(ec_graph()))
        assert "nodes" in result
        assert "edges" in result
        assert "stats" in result
        assert result["stats"]["total_nodes"] > 0

    def test_graph_with_session_filter(self, mock_repo_db):
        from entirecontext.mcp.server import ec_graph

        result = json.loads(asyncio.run(ec_graph(session_id="s1")))
        assert "nodes" in result
        assert result["stats"]["total_nodes"] > 0

    def test_graph_no_repo(self, monkeypatch):
        pytest.importorskip("mcp")
        from entirecontext.mcp.server import ec_graph

        monkeypatch.setattr(
            "entirecontext.mcp.runtime.get_repo_db",
            lambda repo_hint=None: (_ for _ in ()).throw(
                runtime.RepoResolutionError("No repo found. Run 'ec init' in your repo or set ENTIRECONTEXT_REPO_PATH.")
            ),
        )
        result = json.loads(asyncio.run(ec_graph()))
        assert "error" in result


class TestMCPDashboard:
    """Tests for ec_dashboard MCP tool."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        class _NoCloseConn:
            """Proxy that prevents tool finally-blocks from closing the shared fixture connection."""

            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def close(self):
                pass

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

        wrapper = _NoCloseConn(db)
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
        return wrapper

    def test_dashboard_basic(self, mock_repo_db):
        from entirecontext.mcp.server import ec_dashboard

        result = json.loads(asyncio.run(ec_dashboard()))
        assert "sessions" in result
        assert "total" in result["sessions"]
        assert "telemetry" in result
        assert "maturity_score" in result

    def test_dashboard_with_since(self, mock_repo_db):
        from entirecontext.mcp.server import ec_dashboard

        result = json.loads(asyncio.run(ec_dashboard(since="2024-01-01")))
        assert "sessions" in result

    def test_dashboard_no_repo(self, monkeypatch):
        pytest.importorskip("mcp")
        from entirecontext.mcp.server import ec_dashboard

        monkeypatch.setattr(
            "entirecontext.mcp.runtime.get_repo_db",
            lambda repo_hint=None: (_ for _ in ()).throw(
                runtime.RepoResolutionError("No repo found. Run 'ec init' in your repo or set ENTIRECONTEXT_REPO_PATH.")
            ),
        )
        result = json.loads(asyncio.run(ec_dashboard()))
        assert "error" in result

    def test_context_apply(self, mock_repo_db):
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
        from entirecontext.mcp.server import ec_context_apply

        event = record_retrieval_event(
            mock_repo_db,
            source="mcp",
            search_type="regex",
            target="turn",
            query="auth",
            result_count=1,
            latency_ms=5,
            session_id="s1",
            turn_id="t1",
        )
        selection = record_retrieval_selection(mock_repo_db, event["id"], "assessment", "asmt-1")
        result = json.loads(asyncio.run(ec_context_apply("lesson_applied", selection_id=selection["id"])))
        assert result["application_type"] == "lesson_applied"
        assert result["retrieval_selection_id"] == selection["id"]

    def test_context_apply_auto_records_accepted_outcome(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
        from entirecontext.mcp.server import ec_context_apply

        decision = create_decision(mock_repo_db, title="Auto outcome test")
        event = record_retrieval_event(
            mock_repo_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id="s1",
            turn_id="t1",
        )
        selection = record_retrieval_selection(mock_repo_db, event["id"], "decision", decision["id"])
        asyncio.run(ec_context_apply("decision_change", selection_id=selection["id"]))

        outcomes = mock_repo_db.execute(
            "SELECT outcome_type, note FROM decision_outcomes WHERE decision_id = ?",
            (decision["id"],),
        ).fetchall()
        assert len(outcomes) == 1
        assert outcomes[0]["outcome_type"] == "accepted"
        assert outcomes[0]["note"] == "auto: context_apply"

    def test_context_apply_reference_no_auto_outcome(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
        from entirecontext.mcp.server import ec_context_apply

        decision = create_decision(mock_repo_db, title="Reference no outcome")
        event = record_retrieval_event(
            mock_repo_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id="s1",
            turn_id="t1",
        )
        selection = record_retrieval_selection(mock_repo_db, event["id"], "decision", decision["id"])
        asyncio.run(ec_context_apply("reference", selection_id=selection["id"]))

        outcomes = mock_repo_db.execute(
            "SELECT COUNT(*) AS n FROM decision_outcomes WHERE decision_id = ?",
            (decision["id"],),
        ).fetchone()["n"]
        assert outcomes == 0

    def test_context_apply_auto_accepted_without_selection(self, mock_repo_db):
        """Direct decision apply (no selection_id) must still produce an accepted outcome."""
        from entirecontext.core.decisions import create_decision
        from entirecontext.mcp.server import ec_context_apply

        decision = create_decision(mock_repo_db, title="Direct apply no selection")
        asyncio.run(
            ec_context_apply(
                "decision_change",
                source_type="decision",
                source_id=decision["id"],
            )
        )

        rows = mock_repo_db.execute(
            "SELECT outcome_type, retrieval_selection_id, note FROM decision_outcomes WHERE decision_id = ?",
            (decision["id"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome_type"] == "accepted"
        assert rows[0]["retrieval_selection_id"] is None
        assert rows[0]["note"] == "auto: context_apply"


class TestMCPDecisionTools:
    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        class _NoCloseConn:
            """Proxy that prevents tool finally-blocks from closing the shared fixture connection."""

            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def close(self):
                pass

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

        wrapper = _NoCloseConn(db)
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
        return wrapper

    def test_decision_get_includes_quality_summary(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, record_decision_outcome
        from entirecontext.mcp.server import ec_decision_get

        decision = create_decision(mock_repo_db, title="Use queue retries")
        record_decision_outcome(mock_repo_db, decision["id"], "accepted", note="Applied in worker")

        result = json.loads(asyncio.run(ec_decision_get(decision["id"])))
        assert result["quality_summary"]["counts"]["accepted"] == 1
        assert result["recent_outcomes"][0]["note"] == "Applied in worker"

    def test_decision_outcome_records_with_selection(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
        from entirecontext.mcp.server import ec_decision_outcome

        decision = create_decision(mock_repo_db, title="Use queue retries")
        event = record_retrieval_event(
            mock_repo_db,
            source="mcp",
            search_type="decision_related",
            target="decision",
            query="retries",
            result_count=1,
            latency_ms=5,
            session_id="s1",
            turn_id="t1",
        )
        selection = record_retrieval_selection(mock_repo_db, event["id"], "decision", decision["id"])

        result = json.loads(
            asyncio.run(
                ec_decision_outcome(
                    decision["id"][:12],
                    "accepted",
                    selection_id=selection["id"],
                    note="Applied in worker",
                )
            )
        )
        assert result["decision_id"] == decision["id"]
        assert result["retrieval_selection_id"] == selection["id"]
        assert result["outcome_type"] == "accepted"

    @pytest.mark.parametrize("outcome_value", ["accepted", "ignored", "contradicted", "refined", "replaced"])
    def test_decision_outcome_accepts_all_five_values(self, mock_repo_db, outcome_value):
        from entirecontext.core.decisions import create_decision
        from entirecontext.mcp.server import ec_decision_outcome

        decision = create_decision(mock_repo_db, title=f"MCP outcome {outcome_value}")
        result = json.loads(asyncio.run(ec_decision_outcome(decision["id"][:12], outcome_value)))
        assert result["outcome_type"] == outcome_value

    def test_decision_outcome_rejects_non_decision_selection(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
        from entirecontext.mcp.server import ec_decision_outcome

        decision = create_decision(mock_repo_db, title="Use queue retries")
        event = record_retrieval_event(
            mock_repo_db,
            source="mcp",
            search_type="regex",
            target="turn",
            query="retries",
            result_count=1,
            latency_ms=5,
            session_id="s1",
            turn_id="t1",
        )
        selection = record_retrieval_selection(mock_repo_db, event["id"], "turn", "t1")

        result = json.loads(asyncio.run(ec_decision_outcome(decision["id"], "accepted", selection_id=selection["id"])))
        assert "error" in result
        assert "must point to a decision" in result["error"]

    def test_decision_outcome_uses_selection_context_when_current_session_has_no_turns(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision
        from entirecontext.core.session import create_session
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
        from entirecontext.mcp.server import ec_decision_outcome

        decision = create_decision(mock_repo_db, title="Use queue retries")
        event = record_retrieval_event(
            mock_repo_db,
            source="mcp",
            search_type="decision_related",
            target="decision",
            query="retries",
            result_count=1,
            latency_ms=5,
            session_id="s1",
            turn_id="t1",
        )
        selection = record_retrieval_selection(mock_repo_db, event["id"], "decision", decision["id"])
        create_session(mock_repo_db, "p1", session_id="s2")

        result = json.loads(asyncio.run(ec_decision_outcome(decision["id"], "accepted", selection_id=selection["id"])))
        assert result["session_id"] == "s1"
        assert result["turn_id"] == "t1"


class TestMCPActivate:
    """Tests for ec_activate MCP tool."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (db, "/tmp/test"))
        db.execute(
            "UPDATE turns SET files_touched = ? WHERE id = 't1'",
            (json.dumps(["src/auth.py"]),),
        )
        db.execute(
            "UPDATE turns SET files_touched = ? WHERE id = 't2'",
            (json.dumps(["src/auth.py", "src/test.py"]),),
        )
        db.commit()
        return db

    def test_activate_by_turn(self, mock_repo_db):
        from entirecontext.mcp.server import ec_activate

        result = json.loads(asyncio.run(ec_activate(seed_turn_id="t1")))
        assert "results" in result
        assert result["count"] >= 1

    def test_activate_no_seed(self, mock_repo_db):
        from entirecontext.mcp.server import ec_activate

        result = json.loads(asyncio.run(ec_activate()))
        assert "error" in result

    def test_activate_no_repo(self, monkeypatch):
        pytest.importorskip("mcp")
        from entirecontext.mcp.server import ec_activate

        monkeypatch.setattr(
            "entirecontext.mcp.runtime.get_repo_db",
            lambda repo_hint=None: (_ for _ in ()).throw(
                runtime.RepoResolutionError("No repo found. Run 'ec init' in your repo or set ENTIRECONTEXT_REPO_PATH.")
            ),
        )
        result = json.loads(asyncio.run(ec_activate(seed_turn_id="t1")))
        assert "error" in result


class TestMcpQueryRedaction:
    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db_with_secret(self, db, monkeypatch):
        db.execute(
            "UPDATE turns SET user_message = 'fix password=secret123', assistant_summary = 'Fixed token=abc123' WHERE id = 't1'"
        )
        db.commit()
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (db, "/tmp/test"))
        redaction_config = {
            "filtering": {
                "query_redaction": {
                    "enabled": True,
                    "patterns": [r"password\s*=\s*\S+", r"token\s*=\s*\S+"],
                    "replacement": "[FILTERED]",
                }
            },
            "capture": {"exclusions": {"enabled": False}},
        }
        monkeypatch.setattr("entirecontext.core.config.load_config", lambda *a, **kw: redaction_config)
        return db

    def test_ec_search_applies_redaction(self, mock_repo_db_with_secret):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("password")))
        assert result["count"] >= 1
        for r in result["results"]:
            assert "secret123" not in r.get("summary", "")

    def test_ec_turn_content_applies_redaction(self, mock_repo_db_with_secret):
        from entirecontext.mcp.server import ec_turn_content

        result = json.loads(asyncio.run(ec_turn_content("t1")))
        assert "secret123" not in result.get("user_message", "")
        assert "abc123" not in result.get("assistant_summary", "")


class TestMCPDecisionToolsExtended:
    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (db, "/tmp/test"))
        return db

    def test_ec_decision_related_with_files(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_related

        decision = create_decision(mock_repo_db, title="Use WAL mode")
        link_decision_to_file(mock_repo_db, decision["id"], "src/db.py")

        result = json.loads(asyncio.run(ec_decision_related(files=["src/db.py"])))
        assert result["count"] >= 1
        ids = [d["id"] for d in result["decisions"]]
        assert decision["id"] in ids

    def test_ec_decision_related_records_selection(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_related

        decision = create_decision(mock_repo_db, title="Index strategy")
        link_decision_to_file(mock_repo_db, decision["id"], "src/index.py")

        result = json.loads(asyncio.run(ec_decision_related(files=["src/index.py"])))
        assert result["retrieval_event_id"] is not None
        assert result["count"] >= 1
        assert any(d["id"] == decision["id"] for d in result["decisions"])

    def test_ec_decision_create_with_alternatives(self, mock_repo_db):
        from entirecontext.mcp.tools.decisions import ec_decision_create

        result = json.loads(
            asyncio.run(
                ec_decision_create(
                    title="Use SQLite",
                    rationale="Lightweight and embedded",
                    scope="storage",
                    rejected_alternatives=["PostgreSQL", "MySQL"],
                    supporting_evidence=[{"source": "benchmark", "result": "fast"}],
                )
            )
        )
        assert result["title"] == "Use SQLite"
        assert result["rationale"] == "Lightweight and embedded"
        assert result["scope"] == "storage"
        assert result["rejected_alternatives"] == ["PostgreSQL", "MySQL"]
        assert result["supporting_evidence"] == [{"source": "benchmark", "result": "fast"}]

    def test_ec_decision_list_with_file_filter(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_list

        d1 = create_decision(mock_repo_db, title="Decision A")
        d2 = create_decision(mock_repo_db, title="Decision B")
        link_decision_to_file(mock_repo_db, d1["id"], "src/special.py")

        result = json.loads(asyncio.run(ec_decision_list(file_path="src/special.py")))
        ids = [d["id"] for d in result["decisions"]]
        assert d1["id"] in ids
        assert d2["id"] not in ids

    def test_ec_decision_list_with_staleness_filter(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, update_decision_staleness
        from entirecontext.mcp.tools.decisions import ec_decision_list

        d_fresh = create_decision(mock_repo_db, title="Fresh decision")
        d_stale = create_decision(mock_repo_db, title="Stale decision")
        update_decision_staleness(mock_repo_db, d_stale["id"], "stale")

        result = json.loads(asyncio.run(ec_decision_list(staleness_status="fresh")))
        ids = [d["id"] for d in result["decisions"]]
        assert d_fresh["id"] in ids
        assert d_stale["id"] not in ids

    def test_ec_decision_list_excludes_contradicted_by_default(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, update_decision_staleness
        from entirecontext.mcp.tools.decisions import ec_decision_list

        d_fresh = create_decision(mock_repo_db, title="Fresh visible")
        d_contradicted = create_decision(mock_repo_db, title="Contradicted hidden")
        update_decision_staleness(mock_repo_db, d_contradicted["id"], "contradicted")

        # Default: contradicted excluded (fixture returns raw conn — single MCP call only)
        result = json.loads(asyncio.run(ec_decision_list()))
        ids = [d["id"] for d in result["decisions"]]
        assert d_fresh["id"] in ids
        assert d_contradicted["id"] not in ids

    def test_ec_decision_list_includes_contradicted_when_requested(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, update_decision_staleness
        from entirecontext.mcp.tools.decisions import ec_decision_list

        d_fresh = create_decision(mock_repo_db, title="Fresh opt-in")
        d_contradicted = create_decision(mock_repo_db, title="Contradicted opt-in")
        update_decision_staleness(mock_repo_db, d_contradicted["id"], "contradicted")

        result = json.loads(asyncio.run(ec_decision_list(include_contradicted=True)))
        ids = [d["id"] for d in result["decisions"]]
        assert d_fresh["id"] in ids
        assert d_contradicted["id"] in ids

    def test_ec_decision_stale_check(self, mock_repo_db, monkeypatch):
        from unittest.mock import patch

        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_stale

        decision = create_decision(mock_repo_db, title="Check staleness")
        link_decision_to_file(mock_repo_db, decision["id"], "src/changed.py")

        with patch("entirecontext.core.decisions.subprocess.run") as mock_git:
            mock_git.return_value.returncode = 0
            mock_git.return_value.stdout = "src/changed.py\n"
            result = json.loads(asyncio.run(ec_decision_stale(decision["id"])))

        assert "stale" in result
        assert result["decision_id"] == decision["id"]
        assert result["stale"] is True
        assert "src/changed.py" in result["changed_files"]


class TestMCPStalenessHardening:
    """Issue #39 regression: MCP-level validation of staleness filtering."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        class _NoCloseConn:
            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def close(self):
                pass

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

        wrapper = _NoCloseConn(db)
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
        return wrapper

    def test_ec_decision_related_excludes_superseded(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, link_decision_to_file, supersede_decision
        from entirecontext.mcp.tools.decisions import ec_decision_related

        a = create_decision(mock_repo_db, title="Old")
        b = create_decision(mock_repo_db, title="New")
        link_decision_to_file(mock_repo_db, a["id"], "src/config.py")
        link_decision_to_file(mock_repo_db, b["id"], "src/config.py")
        supersede_decision(mock_repo_db, a["id"], b["id"])

        result = json.loads(asyncio.run(ec_decision_related(files=["src/config.py"])))
        ids = [d["id"] for d in result["decisions"]]
        assert b["id"] in ids
        assert a["id"] not in ids

    def test_ec_decision_related_returns_filter_stats(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, link_decision_to_file, update_decision_staleness
        from entirecontext.mcp.tools.decisions import ec_decision_related

        fresh = create_decision(mock_repo_db, title="Keep")
        bad = create_decision(mock_repo_db, title="Drop")
        link_decision_to_file(mock_repo_db, fresh["id"], "src/router.py")
        link_decision_to_file(mock_repo_db, bad["id"], "src/router.py")
        update_decision_staleness(mock_repo_db, bad["id"], "contradicted")

        result = json.loads(asyncio.run(ec_decision_related(files=["src/router.py"], include_filter_stats=True)))
        assert "filter_stats" in result
        assert result["filter_stats"]["filtered_count"] >= 1

    def test_ec_decision_get_includes_successor(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, supersede_decision
        from entirecontext.mcp.tools.decisions import ec_decision_get

        a = create_decision(mock_repo_db, title="Pre")
        b = create_decision(mock_repo_db, title="Post")
        supersede_decision(mock_repo_db, a["id"], b["id"])

        result = json.loads(asyncio.run(ec_decision_get(a["id"])))
        assert result.get("successor") == {"id": b["id"], "title": "Post"}

    def test_ec_decision_search_contradicted_default_excluded(self, mock_repo_db):
        from entirecontext.core.decisions import create_decision, update_decision_staleness
        from entirecontext.mcp.tools.decisions import ec_decision_search

        d = create_decision(mock_repo_db, title="searchkeywordxray")
        update_decision_staleness(mock_repo_db, d["id"], "contradicted")

        # Default: include_contradicted=False — contradicted excluded.
        default_result = json.loads(asyncio.run(ec_decision_search(query="searchkeywordxray", search_type="fts")))
        default_ids = [r["id"] for r in default_result["decisions"]]
        assert d["id"] not in default_ids

        # Explicit opt-in: contradicted included.
        inclusive_result = json.loads(
            asyncio.run(ec_decision_search(query="searchkeywordxray", search_type="fts", include_contradicted=True))
        )
        inclusive_ids = [r["id"] for r in inclusive_result["decisions"]]
        assert d["id"] in inclusive_ids


class TestEcDecisionContext:
    """Issue #42 regression: one-call proactive retrieval from session context.

    Uses a fresh in-memory DB fixture (not the shared ``db`` fixture) so the
    test controls sessions and turns exactly and can exercise the no-session
    graceful-degradation path.
    """

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def empty_db(self):
        conn = get_memory_db()
        init_schema(conn)
        conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        conn.commit()
        yield conn
        conn.close()

    @pytest.fixture
    def mock_repo_db(self, empty_db, monkeypatch):
        class _NoCloseConn:
            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def close(self):
                pass

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

        wrapper = _NoCloseConn(empty_db)
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
        return wrapper

    @pytest.fixture
    def no_git_subprocess(self, monkeypatch):
        """Stub subprocess.run so the tool doesn't spawn real git against /tmp/test."""
        import subprocess

        def fake_run(*args, **kwargs):
            raise FileNotFoundError("git not available in test")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return fake_run

    def _create_session(self, db, session_id="s1"):
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, "
            "session_title, session_summary, total_turns) "
            "VALUES (?, 'p1', 'claude', '2025-01-01', '2025-01-01', 'ctx', 'ctx', 0)",
            (session_id,),
        )
        db.commit()
        return session_id

    def _create_turn(self, db, turn_id, session_id, turn_number, files_touched):
        db.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, "
            "content_hash, timestamp, files_touched, turn_status) "
            "VALUES (?, ?, ?, 'u', 'a', 'h', '2025-01-01', ?, 'completed')",
            (turn_id, session_id, turn_number, json.dumps(files_touched)),
        )
        db.commit()

    def test_assembles_files_from_last_turns(self, mock_repo_db, no_git_subprocess):
        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)
        self._create_turn(mock_repo_db, "t-old", "s1", 1, ["src/old.py"])
        self._create_turn(mock_repo_db, "t-new", "s1", 2, ["src/new.py"])

        decision = create_decision(mock_repo_db, title="Arch choice")
        link_decision_to_file(mock_repo_db, decision["id"], "src/new.py")

        result = json.loads(asyncio.run(ec_decision_context(recent_turns=5)))
        ids = [d["id"] for d in result["decisions"]]
        assert decision["id"] in ids
        assert result["signal_summary"]["active_session"] is True
        assert result["signal_summary"]["file_count"] >= 2  # both turns' files unioned

    def test_records_retrieval_event_and_selections(self, mock_repo_db, no_git_subprocess):
        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)
        self._create_turn(mock_repo_db, "t1", "s1", 1, ["src/a.py"])
        decision = create_decision(mock_repo_db, title="A")
        link_decision_to_file(mock_repo_db, decision["id"], "src/a.py")

        result = json.loads(asyncio.run(ec_decision_context()))
        assert result["retrieval_event_id"] is not None

        # selection_id threaded through per-decision
        for d in result["decisions"]:
            assert "selection_id" in d

        row = mock_repo_db.execute(
            "SELECT search_type, source FROM retrieval_events WHERE id = ?",
            (result["retrieval_event_id"],),
        ).fetchone()
        assert row is not None
        assert row["search_type"] == "decision_context"
        assert row["source"] == "mcp"

        sel_count = mock_repo_db.execute(
            "SELECT COUNT(*) AS n FROM retrieval_selections WHERE retrieval_event_id = ?",
            (result["retrieval_event_id"],),
        ).fetchone()["n"]
        assert sel_count == len(result["decisions"])

    def test_degrades_when_no_active_session(self, mock_repo_db, no_git_subprocess):
        """P0-3 regression: no active session must not hard-error."""
        from entirecontext.mcp.tools.decisions import ec_decision_context

        result = json.loads(asyncio.run(ec_decision_context()))
        assert "error" not in result
        assert result["signal_summary"]["active_session"] is False
        assert any("No active session" in w for w in result.get("warnings", []))

    def test_git_diff_failure_graceful(self, mock_repo_db, no_git_subprocess):
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)
        result = json.loads(asyncio.run(ec_decision_context()))
        assert "error" not in result
        assert result["signal_summary"]["has_diff"] is False
        assert any("git diff HEAD unavailable" in w for w in result.get("warnings", []))

    def test_empty_when_no_signals_and_no_decisions(self, mock_repo_db, no_git_subprocess):
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)
        result = json.loads(asyncio.run(ec_decision_context()))
        assert "error" not in result
        assert result["count"] == 0
        assert result["decisions"] == []

    def test_git_diff_non_zero_exit_records_warning(self, mock_repo_db, monkeypatch):
        """PR #56 round 6: non-zero `git diff HEAD` exits (e.g. pre-first-commit
        repo) must surface as an explicit warning, not silently drop the
        diff/file signals. `subprocess.run(check=False)` swallows the
        non-zero exit, so the code path has to inspect `returncode`
        explicitly.
        """
        import subprocess

        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)

        def fake_run(args, **kwargs):
            # Simulate `git diff HEAD` exiting 128 with a typical
            # pre-first-commit error on stderr.
            return subprocess.CompletedProcess(
                args,
                128,
                stdout="",
                stderr="fatal: bad revision 'HEAD'\n",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = json.loads(asyncio.run(ec_decision_context()))
        assert "error" not in result
        assert result["signal_summary"]["has_diff"] is False
        assert any("non-zero" in w for w in result.get("warnings", []))

    def test_honors_include_stale_false(self, mock_repo_db, no_git_subprocess):
        from entirecontext.core.decisions import create_decision, link_decision_to_file, update_decision_staleness
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)
        self._create_turn(mock_repo_db, "t1", "s1", 1, ["src/stalefile.py"])

        d = create_decision(mock_repo_db, title="Stale guidance")
        link_decision_to_file(mock_repo_db, d["id"], "src/stalefile.py")
        update_decision_staleness(mock_repo_db, d["id"], "stale")

        result = json.loads(asyncio.run(ec_decision_context(include_stale=False)))
        ids = [r["id"] for r in result["decisions"]]
        assert d["id"] not in ids

    def test_unions_diff_files_not_in_files_touched(self, mock_repo_db, monkeypatch):
        """P1-1 regression: git diff --name-only picks up files that turns.files_touched
        doesn't capture (e.g. MultiEdit edits[].file_path, NotebookEdit notebook_path).
        """
        import subprocess

        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)
        # Session has no file in files_touched
        self._create_turn(mock_repo_db, "t1", "s1", 1, [])
        decision = create_decision(mock_repo_db, title="Multi-edit context")
        link_decision_to_file(mock_repo_db, decision["id"], "src/multi.py")

        def fake_run(args, **kwargs):
            completed = subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if "--name-only" in args:
                completed.stdout = "src/multi.py\n"
            else:
                completed.stdout = "+++ b/src/multi.py\n@@ -1 +1 @@\n+x"
            return completed

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = json.loads(asyncio.run(ec_decision_context()))
        ids = [r["id"] for r in result["decisions"]]
        assert decision["id"] in ids
        assert result["signal_summary"]["file_count"] >= 1
        assert result["signal_summary"]["has_diff"] is True

    def test_session_id_override_targets_specific_session(self, mock_repo_db, no_git_subprocess):
        """PR #56 round 4: explicit session_id must bypass detect_current_context
        so concurrent sessions in the same repo can target their own workflow.
        Uses disjoint directories so proximity matching can't cross-contaminate.
        """
        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_context

        # Two sessions in the same repo, each with files under separate
        # top-level directories so ancestor proximity can't leak.
        self._create_session(mock_repo_db, session_id="session-A")
        self._create_turn(mock_repo_db, "tA-1", "session-A", 1, ["alpha_pkg/runner.py"])
        self._create_session(mock_repo_db, session_id="session-B")
        self._create_turn(mock_repo_db, "tB-1", "session-B", 1, ["beta_pkg/runner.py"])

        d_a = create_decision(mock_repo_db, title="Alpha decision")
        link_decision_to_file(mock_repo_db, d_a["id"], "alpha_pkg/runner.py")
        d_b = create_decision(mock_repo_db, title="Beta decision")
        link_decision_to_file(mock_repo_db, d_b["id"], "beta_pkg/runner.py")

        result_a = json.loads(asyncio.run(ec_decision_context(session_id="session-A")))
        ids_a = [d["id"] for d in result_a["decisions"]]
        assert d_a["id"] in ids_a
        assert d_b["id"] not in ids_a

        result_b = json.loads(asyncio.run(ec_decision_context(session_id="session-B")))
        ids_b = [d["id"] for d in result_b["decisions"]]
        assert d_b["id"] in ids_b
        assert d_a["id"] not in ids_b

    def test_session_id_override_unknown_returns_error(self, mock_repo_db, no_git_subprocess):
        from entirecontext.mcp.tools.decisions import ec_decision_context

        result = json.loads(asyncio.run(ec_decision_context(session_id="does-not-exist")))
        assert "error" in result
        assert "does-not-exist" in result["error"]

    def test_session_id_override_skips_repo_wide_git_diff(self, mock_repo_db, monkeypatch):
        """[Codex P1] When ``session_id`` is explicitly overridden, ``ec_decision_context``
        must NOT spawn ``git diff HEAD``: that diff reflects the working-tree state
        for ALL concurrent sessions in the repo and would leak files from other
        sessions into the session-pinned query. The override path accepts the
        coverage loss in exchange for multi-session correctness.
        """
        import subprocess

        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db, session_id="s-pinned")
        self._create_turn(mock_repo_db, "t-pin-1", "s-pinned", 1, ["alpha_pkg/runner.py"])

        subprocess_calls: list = []

        def tracking_run(args, **kwargs):
            subprocess_calls.append(list(args) if hasattr(args, "__iter__") else args)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", tracking_run)

        result = json.loads(asyncio.run(ec_decision_context(session_id="s-pinned")))
        assert "error" not in result
        assert subprocess_calls == [], (
            f"subprocess.run must not be invoked when session_id is overridden; got calls: {subprocess_calls}"
        )
        assert result["signal_summary"]["has_diff"] is False
        assert any("session_id override" in w for w in result.get("warnings", [])), (
            "override path must record a warning documenting the skipped diff signal"
        )

    def test_session_id_override_attributes_event_to_override_session(self, mock_repo_db, no_git_subprocess):
        """[Codex P1] retrieval_events (and inherited retrieval_selections)
        must be attributed to the overridden ``session_id``, not re-detected via
        ``detect_current_context``. Sets up session-B with a more recent
        ``last_activity_at`` than session-A so the auto-detect fallback would
        return B; then overrides to A and asserts the event row carries A.
        """
        from entirecontext.core.decisions import create_decision, link_decision_to_file
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db, session_id="session-A")
        mock_repo_db.execute("UPDATE sessions SET last_activity_at = '2025-01-01' WHERE id = 'session-A'")
        self._create_session(mock_repo_db, session_id="session-B")
        mock_repo_db.execute("UPDATE sessions SET last_activity_at = '2099-12-31' WHERE id = 'session-B'")
        mock_repo_db.commit()

        self._create_turn(mock_repo_db, "tA", "session-A", 1, ["alpha_pkg/runner.py"])
        d_a = create_decision(mock_repo_db, title="Alpha decision")
        link_decision_to_file(mock_repo_db, d_a["id"], "alpha_pkg/runner.py")

        result = json.loads(asyncio.run(ec_decision_context(session_id="session-A")))
        assert "error" not in result
        event_id = result["retrieval_event_id"]
        assert event_id

        event_row = mock_repo_db.execute("SELECT session_id FROM retrieval_events WHERE id = ?", (event_id,)).fetchone()
        assert event_row["session_id"] == "session-A", (
            "retrieval_events row must be attributed to the override session, "
            "not re-detected via detect_current_context (which would return session-B)"
        )

        # Selections inherit from the event row and must also carry session-A.
        if result["decisions"]:
            selection_id = result["decisions"][0]["selection_id"]
            sel_row = mock_repo_db.execute(
                "SELECT session_id FROM retrieval_selections WHERE id = ?", (selection_id,)
            ).fetchone()
            assert sel_row["session_id"] == "session-A"

    def test_commit_signal_bounded_to_single_sha(self, mock_repo_db, no_git_subprocess, monkeypatch):
        """P1-3 regression: even with many checkpoints, only the latest SHA feeds
        the commit signal so it can't drown current-change context."""
        from entirecontext.core import decisions as core_decisions
        from entirecontext.mcp.tools.decisions import ec_decision_context

        self._create_session(mock_repo_db)
        for i in range(10):
            mock_repo_db.execute(
                "INSERT INTO checkpoints (id, session_id, git_commit_hash, created_at) VALUES (?, 's1', ?, ?)",
                (f"cp-{i}", f"sha-{i}", f"2025-01-{i + 1:02d}"),
            )
        mock_repo_db.commit()

        captured: dict[str, object] = {}
        real_rank = core_decisions.rank_related_decisions

        def spy_rank(conn, **kwargs):
            captured["commit_shas"] = list(kwargs.get("commit_shas") or [])
            return real_rank(conn, **kwargs)

        monkeypatch.setattr("entirecontext.core.decisions.rank_related_decisions", spy_rank)

        asyncio.run(ec_decision_context())

        shas = captured.get("commit_shas")
        assert shas is not None
        assert len(shas) == 1  # only latest, not 10
        assert shas[0] == "sha-9"  # most-recent created_at


class TestMCPAssessTrends:
    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (db, "/tmp/test"))
        return db

    def _seed_assessments(self, conn, count=3, verdict="expand", created_at="2025-06-01", feedback=None):
        from uuid import uuid4

        for _ in range(count):
            aid = str(uuid4())
            conn.execute(
                "INSERT INTO assessments (id, verdict, impact_summary, created_at, feedback) VALUES (?, ?, ?, ?, ?)",
                (aid, verdict, "test impact", created_at, feedback),
            )
        conn.commit()

    def _mock_cross_repo(self, monkeypatch, db):
        from unittest.mock import MagicMock

        mock_registry = MagicMock()
        mock_registry.list_repos.return_value = [{"repo_name": "test", "repo_path": "/tmp/test", "db_path": ":memory:"}]
        mock_policy = MagicMock()
        mock_policy.lazy_pull_repos.return_value = None

        def patched_trends(repos=None, since=None, include_warnings=False):
            from entirecontext.core.futures import list_assessments

            assessments = list_assessments(db, limit=10000)
            if since:
                assessments = [a for a in assessments if a.get("created_at", "") >= since]

            counts = {"expand": 0, "narrow": 0, "neutral": 0}
            with_feedback = 0
            for a in assessments:
                v = a.get("verdict", "neutral")
                if v in counts:
                    counts[v] += 1
                if a.get("feedback"):
                    with_feedback += 1

            result = {
                "total_count": sum(counts.values()),
                "with_feedback": with_feedback,
                "overall": counts,
                "by_repo": {},
            }
            if include_warnings:
                return result, []
            return result

        monkeypatch.setattr("entirecontext.core.cross_repo.cross_repo_assessment_trends", patched_trends)

    def test_ec_assess_trends_basic(self, mock_repo_db, monkeypatch):
        from entirecontext.mcp.tools.futures import ec_assess_trends

        self._seed_assessments(mock_repo_db, count=2, verdict="expand")
        self._seed_assessments(mock_repo_db, count=1, verdict="narrow", feedback="agree")
        self._mock_cross_repo(monkeypatch, mock_repo_db)

        result = json.loads(asyncio.run(ec_assess_trends()))
        assert result["total_count"] == 3
        assert result["overall"]["expand"] == 2
        assert result["overall"]["narrow"] == 1
        assert result["with_feedback"] == 1

    def test_ec_assess_trends_with_since(self, mock_repo_db, monkeypatch):
        from entirecontext.mcp.tools.futures import ec_assess_trends

        self._seed_assessments(mock_repo_db, count=2, verdict="expand", created_at="2025-01-01")
        self._seed_assessments(mock_repo_db, count=1, verdict="neutral", created_at="2025-06-01")
        self._mock_cross_repo(monkeypatch, mock_repo_db)

        result = json.loads(asyncio.run(ec_assess_trends(since="2025-03-01")))
        assert result["total_count"] == 1
        assert result["overall"]["neutral"] == 1
        assert result["overall"]["expand"] == 0

    def test_ec_assess_trends_empty(self, mock_repo_db, monkeypatch):
        from entirecontext.mcp.tools.futures import ec_assess_trends

        self._mock_cross_repo(monkeypatch, mock_repo_db)

        result = json.loads(asyncio.run(ec_assess_trends()))
        assert result["total_count"] == 0
        assert result["with_feedback"] == 0
        assert result["overall"]["expand"] == 0
