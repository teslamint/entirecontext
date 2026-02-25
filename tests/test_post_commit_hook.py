"""Tests for PostCommit hook → checkpoint creation."""

from __future__ import annotations

import json
from unittest.mock import patch



class TestOnPostCommit:
    def test_active_session_creates_checkpoint(self, ec_repo, ec_db):
        from entirecontext.core.session import create_session
        from entirecontext.db import get_db
        from entirecontext.hooks.session_lifecycle import on_post_commit

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        create_session(ec_db, project_id)
        ec_db.close()

        on_post_commit({"cwd": str(ec_repo)})

        conn = get_db(str(ec_repo))
        checkpoints = conn.execute("SELECT * FROM checkpoints").fetchall()
        conn.close()
        assert len(checkpoints) == 1
        meta = json.loads(checkpoints[0]["metadata"])
        assert meta["source"] == "post_commit"

    def test_no_active_session_noop(self, ec_repo, ec_db):
        from entirecontext.db import get_db
        from entirecontext.hooks.session_lifecycle import on_post_commit

        ec_db.close()

        on_post_commit({"cwd": str(ec_repo)})

        conn = get_db(str(ec_repo))
        checkpoints = conn.execute("SELECT * FROM checkpoints").fetchall()
        conn.close()
        assert len(checkpoints) == 0

    def test_exception_does_not_crash(self, ec_repo):
        from entirecontext.hooks.session_lifecycle import on_post_commit

        with patch("entirecontext.hooks.session_lifecycle._find_git_root", side_effect=RuntimeError("boom")):
            on_post_commit({"cwd": str(ec_repo)})

    def test_no_git_commit_skips(self, ec_repo, ec_db):
        from entirecontext.core.session import create_session
        from entirecontext.hooks.session_lifecycle import on_post_commit

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        create_session(ec_db, project_id)
        ec_db.close()

        with patch("entirecontext.core.git_utils.get_current_commit", return_value=None):
            with patch("entirecontext.core.checkpoint.create_checkpoint") as mock_create:
                on_post_commit({"cwd": str(ec_repo)})
                mock_create.assert_not_called()

    def test_no_git_root_skips(self):
        from entirecontext.hooks.session_lifecycle import on_post_commit

        with patch("entirecontext.hooks.session_lifecycle._find_git_root", return_value=None):
            with patch("entirecontext.core.checkpoint.create_checkpoint") as mock_create:
                on_post_commit({"cwd": "/nonexistent"})
                mock_create.assert_not_called()

    def test_diff_uses_previous_checkpoint(self, ec_repo, ec_db):
        from entirecontext.core.checkpoint import create_checkpoint
        from entirecontext.core.session import create_session
        from entirecontext.hooks.session_lifecycle import on_post_commit

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        session_id = session["id"]

        create_checkpoint(
            ec_db,
            session_id=session_id,
            git_commit_hash="abc123prior",
            git_branch="main",
            metadata={"source": "manual"},
        )
        ec_db.close()

        with patch("entirecontext.core.git_utils.get_diff_stat", return_value="1 file changed") as mock_diff:
            on_post_commit({"cwd": str(ec_repo)})
            mock_diff.assert_called_once()
            call_kwargs = mock_diff.call_args
            assert call_kwargs[1].get("from_commit") == "abc123prior" or call_kwargs[0][1] == "abc123prior"


class TestPostCommitDispatch:
    def test_dispatch_routes_post_commit(self):
        from entirecontext.hooks.handler import handle_hook

        with patch("entirecontext.hooks.session_lifecycle.on_post_commit") as mock:
            handle_hook("PostCommit", data={"cwd": "/tmp/test"})
            mock.assert_called_once()

    def test_unknown_hook_still_returns_zero(self):
        from entirecontext.hooks.handler import handle_hook

        assert handle_hook("NonExistent", data={}) == 0
