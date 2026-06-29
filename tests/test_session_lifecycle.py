"""Tests for session_lifecycle hook functions."""

from __future__ import annotations

import json


class TestStopHookExtraction:
    """Stop hook triggers extraction as SessionEnd fallback."""

    def test_stop_triggers_extraction(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.session_lifecycle import on_stop
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        for i in range(4):
            turn = create_turn(
                ec_db,
                session_id=session["id"],
                turn_number=i + 1,
                user_message=f"msg {i}",
                assistant_summary="We decided to use Redis" if i == 0 else f"done {i}",
                turn_status="completed",
            )
            ec_db.execute(
                "UPDATE turns SET files_touched = ? WHERE id = ?",
                (json.dumps(["src/cache.py"]), turn["id"]),
            )
        ec_db.commit()

        extracted = []
        monkeypatch.setattr(
            "entirecontext.hooks.session_lifecycle._maybe_extract_decisions",
            lambda repo, sid: extracted.append(sid),
        )

        on_stop({"session_id": session["id"], "cwd": str(ec_repo)})

        assert session["id"] in extracted

    def test_stop_noop_when_no_session_id(self, ec_repo, monkeypatch):
        """on_stop returns early when session_id is missing."""
        from entirecontext.hooks.session_lifecycle import on_stop

        extracted = []
        monkeypatch.setattr(
            "entirecontext.hooks.session_lifecycle._maybe_extract_decisions",
            lambda repo, sid: extracted.append(sid),
        )

        on_stop({"cwd": str(ec_repo)})

        assert extracted == []
