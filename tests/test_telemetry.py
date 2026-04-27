from __future__ import annotations

import pytest

from entirecontext.core.project import get_project
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import (
    detect_current_context,
    record_context_application,
    record_retrieval_event,
    record_retrieval_selection,
)
from entirecontext.core.turn import create_turn


class TestTelemetryHelpers:
    def test_detect_current_context(self, ec_repo, ec_db):
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="telemetry-session")
        create_turn(ec_db, session["id"], 1, user_message="look up auth", assistant_summary="found auth history")

        session_id, turn_id = detect_current_context(ec_db)
        assert session_id == session["id"]
        assert turn_id is not None

    def test_record_selection_and_apply_from_selection(self, ec_repo, ec_db):
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="telemetry-selection")
        turn = create_turn(ec_db, session["id"], 1, user_message="search auth", assistant_summary="returned results")

        event = record_retrieval_event(
            ec_db,
            source="cli",
            search_type="regex",
            target="turn",
            query="auth",
            result_count=2,
            latency_ms=7,
            session_id=session["id"],
            turn_id=turn["id"],
        )
        selection = record_retrieval_selection(ec_db, event["id"], "turn", "t-source", rank=1)
        application = record_context_application(
            ec_db,
            application_type="reference",
            selection_id=selection["id"],
        )

        row = ec_db.execute("SELECT * FROM context_applications WHERE id = ?", (application["id"],)).fetchone()
        assert row["retrieval_selection_id"] == selection["id"]
        assert row["source_type"] == "turn"
        assert row["source_id"] == "t-source"

    def test_direct_application_requires_source(self, ec_db):
        try:
            record_context_application(ec_db, application_type="reference")
        except ValueError as exc:
            assert "source_type and source_id are required" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_invalid_application_type_rejected(self, ec_repo, ec_db):
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="telemetry-invalid")
        create_turn(ec_db, session["id"], 1, user_message="search auth", assistant_summary="returned results")

        try:
            record_context_application(
                ec_db,
                application_type="invalid",
                source_type="assessment",
                source_id="asmt-1",
            )
        except ValueError as exc:
            assert "Invalid application_type" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    @pytest.mark.skip(
        reason="S2b autocommit flip invalidates the v0.3.0 commit=False deferred-commit "
        "contract this test encodes. The `commit` parameter is removed in S2b commit 3 "
        "along with this test."
    )
    def test_commit_false_defers_write(self, ec_repo, ec_db):
        import sqlite3

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="telemetry-defer")
        turn = create_turn(ec_db, session["id"], 1, user_message="test", assistant_summary="ok")

        event = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
            turn_id=turn["id"],
            commit=False,
        )
        sel = record_retrieval_selection(
            ec_db,
            event["id"],
            "decision",
            "d-1",
            rank=1,
            commit=False,
        )

        assert event["id"] is not None
        assert sel["id"] is not None

        # A second connection must NOT see uncommitted rows (deferred-commit contract).
        db_path = str(ec_repo / ".entirecontext" / "db" / "local.db")
        second_conn = sqlite3.connect(db_path)
        try:
            pre = second_conn.execute("SELECT id FROM retrieval_events WHERE id = ?", (event["id"],)).fetchone()
            assert pre is None, "row should not be visible to other connections before commit"
        finally:
            second_conn.close()

        ec_db.commit()

        # After commit, a second connection CAN see the rows.
        second_conn = sqlite3.connect(db_path)
        try:
            post = second_conn.execute("SELECT id FROM retrieval_events WHERE id = ?", (event["id"],)).fetchone()
            assert post is not None, "row should be visible after commit"
            sel_post = second_conn.execute("SELECT id FROM retrieval_selections WHERE id = ?", (sel["id"],)).fetchone()
            assert sel_post is not None, "selection should be visible after commit"
        finally:
            second_conn.close()
