"""Regression test: ended_at is set even when _populate_session_summary raises."""

from __future__ import annotations

import pytest

from entirecontext.db import get_db
from entirecontext.hooks.session_lifecycle import on_session_end, on_session_start


class TestSessionEndOrdering:
    def test_ended_at_set_when_summary_raises(self, ec_repo, monkeypatch):
        """ended_at must be committed before _populate_session_summary is called.

        If summary generation fails (e.g. LLM timeout kills the process after
        the hook timeout), ended_at should already be persisted in the DB.
        """
        cwd = str(ec_repo)
        sid = "ordering-test-session"

        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})

        import entirecontext.hooks.session_lifecycle as lifecycle_mod

        def _raise(*args, **kwargs):
            raise RuntimeError("simulated LLM timeout")

        monkeypatch.setattr(lifecycle_mod, "_populate_session_summary", _raise)

        with pytest.raises(RuntimeError, match="simulated LLM timeout"):
            on_session_end({"session_id": sid, "cwd": cwd})

        conn = get_db(cwd)
        try:
            row = conn.execute("SELECT ended_at FROM sessions WHERE id = ?", (sid,)).fetchone()
            assert row is not None
            assert row["ended_at"] is not None, "ended_at must be set even when summary generation raises"
        finally:
            conn.close()
