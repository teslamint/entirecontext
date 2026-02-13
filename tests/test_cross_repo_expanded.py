"""Expanded tests for cross-repo functions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4


from entirecontext.core.cross_repo import (
    _for_each_repo,
    _lazy_pull_repos,
    _return_with_warnings,
    cross_repo_attribution,
    cross_repo_checkpoints,
    cross_repo_events,
    cross_repo_related,
    cross_repo_rewind,
    cross_repo_session_detail,
    cross_repo_sessions,
    cross_repo_turn_content,
    resolve_content_path,
)


def _seed_checkpoint(conn, session_id, commit_hash="abc123", checkpoint_id=None):
    cid = checkpoint_id or str(uuid4())
    conn.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES (?, ?, ?)",
        (cid, session_id, commit_hash),
    )
    conn.commit()
    return cid


def _seed_event(conn, title="test event", event_type="task"):
    from entirecontext.core.event import create_event

    return create_event(conn, title=title, event_type=event_type)


def _seed_attribution(conn, checkpoint_id, session_id, file_path="src/main.py"):
    aid = str(uuid4())
    conn.execute(
        "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, session_id, confidence) VALUES (?, ?, ?, 1, 10, 'agent', ?, 1.0)",
        (aid, checkpoint_id, file_path, session_id),
    )
    conn.commit()
    return aid


def _get_repo_conn(repo_path):
    from entirecontext.db import get_db, check_and_migrate

    conn = get_db(str(repo_path))
    check_and_migrate(conn)
    return conn


def _get_session_id(conn, name):
    row = conn.execute("SELECT id FROM sessions WHERE id = ?", (f"{name}-session-1",)).fetchone()
    return row["id"] if row else None


class TestForEachRepo:
    def test_merges_results_from_all_repos(self, multi_ec_repos):
        def fn(conn, repo):
            rows = conn.execute("SELECT id FROM sessions LIMIT 5").fetchall()
            return [dict(r) for r in rows]

        results, warnings = _for_each_repo(fn)
        assert len(results) == 2
        assert warnings == []

    def test_sort_key_and_limit(self, multi_ec_repos):
        def fn(conn, repo):
            rows = conn.execute("SELECT id, last_activity_at FROM sessions").fetchall()
            return [dict(r) for r in rows]

        results, warnings = _for_each_repo(fn, sort_key="last_activity_at", limit=1)
        assert len(results) == 1

    def test_partial_failure_adds_warning(self, multi_ec_repos, tmp_path):
        from entirecontext.db import get_global_db
        from entirecontext.db.global_schema import init_global_schema

        gconn = get_global_db()
        init_global_schema(gconn)
        bad_db = tmp_path / "bad.db"
        bad_db.write_text("not sqlite")
        gconn.execute(
            "INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path) VALUES (?, ?, ?)",
            ("/bad", "broken", str(bad_db)),
        )
        gconn.commit()
        gconn.close()

        def fn(conn, repo):
            return [{"x": 1}]

        results, warnings = _for_each_repo(fn)
        assert len(warnings) == 1
        assert "broken" in warnings[0]
        assert len(results) >= 2

    def test_empty_repos_returns_empty(self, isolated_global_db):
        def fn(conn, repo):
            return [{"x": 1}]

        results, warnings = _for_each_repo(fn)
        assert results == []
        assert warnings == []


class TestReturnWithWarnings:
    def test_include_warnings_true(self):
        r, w = _return_with_warnings([{"a": 1}], ["warn1"], include_warnings=True)
        assert r == [{"a": 1}]
        assert w == ["warn1"]

    def test_include_warnings_false(self):
        result = _return_with_warnings([{"a": 1}], ["warn1"], include_warnings=False)
        assert result == [{"a": 1}]
        assert not isinstance(result, tuple)


class TestCrossRepoCheckpoints:
    def test_lists_from_multiple_repos(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            sid = _get_session_id(conn, name)
            _seed_checkpoint(conn, sid, commit_hash=f"hash-{name}")
            conn.close()

        results = cross_repo_checkpoints()
        assert len(results) == 2
        repos = {r["repo_name"] for r in results}
        assert "frontend" in repos
        assert "backend" in repos

    def test_session_id_filter(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            sid = _get_session_id(conn, name)
            _seed_checkpoint(conn, sid)
            conn.close()

        results = cross_repo_checkpoints(session_id="frontend-session-1")
        assert len(results) == 1
        assert results[0]["session_id"] == "frontend-session-1"

    def test_since_filter(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        sid = _get_session_id(conn, "frontend")
        _seed_checkpoint(conn, sid)
        conn.close()

        results = cross_repo_checkpoints(since="2099-01-01T00:00:00")
        assert results == []

    def test_include_warnings_backward_compat(self, multi_ec_repos):
        results = cross_repo_checkpoints(include_warnings=False)
        assert isinstance(results, list)

        results_w = cross_repo_checkpoints(include_warnings=True)
        assert isinstance(results_w, tuple)


class TestCrossRepoSessionDetail:
    def test_found_in_second_repo(self, multi_ec_repos):
        result = cross_repo_session_detail("backend-session-1")
        assert result is not None
        assert result["id"] == "backend-session-1"
        assert "turns" in result
        assert result["repo_name"] == "backend"

    def test_not_found_returns_none(self, multi_ec_repos):
        result = cross_repo_session_detail("nonexistent-session")
        assert result is None

    def test_include_warnings(self, multi_ec_repos):
        result, warnings = cross_repo_session_detail("frontend-session-1", include_warnings=True)
        assert result is not None
        assert isinstance(warnings, list)


class TestCrossRepoEvents:
    def test_lists_from_multiple_repos(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_event(conn, title=f"event-{name}")
            conn.close()

        results = cross_repo_events()
        assert len(results) == 2
        repos = {r["repo_name"] for r in results}
        assert "frontend" in repos
        assert "backend" in repos

    def test_status_filter(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        _seed_event(conn, title="active-event")
        conn.close()

        results = cross_repo_events(status="active")
        assert len(results) >= 1
        assert all(r["status"] == "active" for r in results)

        results_frozen = cross_repo_events(status="frozen")
        assert results_frozen == []


class TestCrossRepoAttribution:
    def test_from_multiple_repos(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            sid = _get_session_id(conn, name)
            cid = _seed_checkpoint(conn, sid)
            _seed_attribution(conn, cid, sid, file_path="shared.py")
            conn.close()

        results = cross_repo_attribution("shared.py")
        assert len(results) == 2
        repos = {r["repo_name"] for r in results}
        assert "frontend" in repos
        assert "backend" in repos

    def test_include_warnings(self, multi_ec_repos):
        results, warnings = cross_repo_attribution("nonexistent.py", include_warnings=True)
        assert isinstance(results, list)
        assert isinstance(warnings, list)


class TestCrossRepoRelated:
    def test_query_search(self, multi_ec_repos):
        results = cross_repo_related(query="auth")
        assert len(results) >= 2
        repos = {r["repo_name"] for r in results}
        assert "frontend" in repos
        assert "backend" in repos

    def test_file_search(self, multi_ec_repos):
        results = cross_repo_related(files=["main.py"])
        assert isinstance(results, list)


class TestCrossRepoRewind:
    def test_found_in_first_repo(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        sid = _get_session_id(conn, "frontend")
        _seed_checkpoint(conn, sid, checkpoint_id="cp-frontend-1")
        conn.close()

        result = cross_repo_rewind("cp-frontend-1")
        assert result is not None
        assert result["id"] == "cp-frontend-1"

    def test_found_in_second_repo(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["backend"])
        sid = _get_session_id(conn, "backend")
        _seed_checkpoint(conn, sid, checkpoint_id="cp-backend-1")
        conn.close()

        result = cross_repo_rewind("cp-backend-1")
        assert result is not None
        assert result["id"] == "cp-backend-1"
        assert result["repo_name"] == "backend"

    def test_not_found(self, multi_ec_repos):
        result = cross_repo_rewind("nonexistent-cp")
        assert result is None

    def test_include_warnings(self, multi_ec_repos):
        result, warnings = cross_repo_rewind("nonexistent-cp", include_warnings=True)
        assert result is None
        assert isinstance(warnings, list)


class TestCrossRepoTurnContent:
    def test_found_with_content_file(self, multi_ec_repos):
        repo_path = multi_ec_repos["frontend"]
        conn = _get_repo_conn(repo_path)
        sid = _get_session_id(conn, "frontend")
        turn = conn.execute("SELECT id FROM turns WHERE session_id = ? LIMIT 1", (sid,)).fetchone()
        turn_id = turn["id"]

        from entirecontext.core.turn import save_turn_content

        save_turn_content(str(repo_path), conn, turn_id, sid, '{"message": "hello"}')
        conn.close()

        result = cross_repo_turn_content(turn_id)
        assert result is not None
        assert result["content"] is not None
        assert "hello" in result["content"]
        assert result["repo_name"] == "frontend"
        assert "content_path" in result

    def test_found_without_content_file(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        sid = _get_session_id(conn, "frontend")
        turn = conn.execute("SELECT id FROM turns WHERE session_id = ? LIMIT 1", (sid,)).fetchone()
        turn_id = turn["id"]
        conn.close()

        result = cross_repo_turn_content(turn_id)
        assert result is not None
        assert result["content"] is None

    def test_not_found(self, multi_ec_repos):
        result = cross_repo_turn_content("nonexistent-turn-id")
        assert result is None

    def test_include_warnings(self, multi_ec_repos):
        result, warnings = cross_repo_turn_content("nonexistent-turn-id", include_warnings=True)
        assert result is None
        assert isinstance(warnings, list)


class TestResolveContentPath:
    def test_resolves_path(self):
        result = resolve_content_path("/repo", "content/sess/turn.jsonl")
        assert result == Path("/repo/.entirecontext/content/sess/turn.jsonl")


class TestBackwardCompat:
    def test_sessions_no_warnings_returns_list(self, multi_ec_repos):
        result = cross_repo_sessions(include_warnings=False)
        assert isinstance(result, list)
        assert not isinstance(result, tuple)

    def test_sessions_with_warnings_returns_tuple(self, multi_ec_repos):
        result = cross_repo_sessions(include_warnings=True)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestLazyPullRepos:
    def test_noop_when_auto_pull_disabled(self, monkeypatch, isolated_global_config):
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda *a, **kw: {"sync": {"auto_pull": False}},
        )
        _lazy_pull_repos([{"repo_path": "/fake", "db_path": "/fake/db"}])

    def test_calls_should_pull_when_enabled(self, monkeypatch, isolated_global_config, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".entirecontext" / "db").mkdir(parents=True)
        db_path = str(repo / ".entirecontext" / "db" / "local.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()

        pull_called = []
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda *a, **kw: {"sync": {"auto_pull": True, "pull_staleness_seconds": 600}},
        )
        monkeypatch.setattr(
            "entirecontext.sync.auto_sync.should_pull",
            lambda conn, config: True,
        )
        monkeypatch.setattr(
            "entirecontext.sync.auto_sync.run_pull",
            lambda repo_path: pull_called.append(repo_path),
        )

        _lazy_pull_repos([{"repo_path": str(repo), "db_path": db_path}])
        assert len(pull_called) == 1
